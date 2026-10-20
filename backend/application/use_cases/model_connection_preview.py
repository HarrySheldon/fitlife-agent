"""Explicit, bounded model configuration previews; never persist configuration."""
import time
from contextlib import contextmanager
from dataclasses import dataclass

from backend.application.ports.model_call_context import remaining_model_timeout
from backend.domain.errors import ApplicationError, credential_store_unavailable_error, model_gateway_error
from backend.domain.model_connection import ModelConnection, utc_now_iso
from backend.domain.model_provider import DEFAULT_PROVIDERS


@dataclass(frozen=True)
class PreviewRatePolicy:
    requests_per_minute: int = 6
    concurrent_runs: int = 1
    anonymous_requests_per_minute: int = 0
    anonymous_concurrent_runs: int = 0


def setup_error(code, message, status=409):
    return ApplicationError(code=code, message=message, status_code=status)


class ModelConnectionPreview:
    def __init__(self, repository, cipher, verification, gateway_factory, endpoint_policy, limiter,
                 *, providers=DEFAULT_PROVIDERS, clock=time.monotonic):
        self.repository, self.cipher, self.verification = repository, cipher, verification
        self.gateway_factory, self.endpoint_policy, self.limiter = gateway_factory, endpoint_policy, limiter
        self.providers, self.clock = providers, clock

    def prepare(self, user_id, payload, *, require_model=True):
        if self.cipher is None or self.verification is None:
            raise credential_store_unavailable_error()
        workspace = self.repository.get_workspace(user_id)
        if workspace.revision != payload.expected_revision:
            raise setup_error("MODEL_CONFIGURATION_CONFLICT", "The model configuration changed. Reload before saving.")
        try:
            self.providers.resolve(payload.provider_id, payload.protocol)
        except ValueError:
            raise setup_error("MODEL_PROVIDER_UNSUPPORTED", "Choose a supported provider and protocol.", 422) from None
        address = self.endpoint_policy.canonical_base_url(payload.base_url)
        model = payload.model.strip()
        if require_model and not model:
            raise setup_error("MODEL_NAME_REQUIRED", "Enter a model ID.", 422)
        if payload.credential_mode == "new":
            credential = payload.api_key.get_secret_value().strip()
        else:
            source = workspace.active if payload.credential_mode == "reuse_active" else workspace.draft
            if source is None or not source.encrypted_api_key:
                raise setup_error("MODEL_CREDENTIAL_REQUIRED", "Provide a model credential.", 422)
            source_address = (source.base_url or "https://api.openai.com/v1").rstrip("/")
            if (source.provider_id or source.provider, source_address) != (payload.provider_id, address):
                if not payload.confirm_credential_reuse:
                    raise setup_error("MODEL_CREDENTIAL_REUSE_CONFIRMATION_REQUIRED",
                        "Confirm sending the saved credential to the new provider address.")
            try:
                credential = self.cipher.decrypt(source.encrypted_api_key)
            except Exception:
                raise credential_store_unavailable_error() from None
        connection = ModelConnection(provider_id=payload.provider_id,
            provider="openai" if payload.provider_id == "openai" else "custom",
            protocol=payload.protocol, base_url=address, model=model, enabled=False)
        binding = {"user_id": user_id, "revision": workspace.revision, "provider_id": payload.provider_id,
            "base_url": address, "protocol": payload.protocol, "model": model,
            "credential_fingerprint": self.verification.fingerprint(credential)}
        return workspace, connection, credential, binding

    @contextmanager
    def _gateway(self, user_id, connection, credential, *, seconds):
        with self.limiter.acquire(user_id, PreviewRatePolicy()):
            deadline = self.clock() + seconds
            def remaining():
                value = deadline - self.clock()
                if value <= 0:
                    raise TimeoutError("Probe deadline reached")
                return value
            token = remaining_model_timeout.set(remaining)
            gateway = None
            try:
                try:
                    gateway = self.gateway_factory(connection, credential)
                except ApplicationError:
                    raise
                except Exception as error:
                    normalized = model_gateway_error(error)
                    raise setup_error(normalized.code, normalized.message, normalized.status_code) from None
                yield gateway, remaining
            finally:
                remaining_model_timeout.reset(token)
                if gateway is not None:
                    close = getattr(gateway, "close", None)
                    if close:
                        try:
                            close()
                        except Exception:
                            pass  # Never expose provider cleanup errors or invalidate a prior failure.

    def list_models(self, user_id, payload):
        _, connection, credential, _ = self.prepare(user_id, payload, require_model=False)
        try:
            with self._gateway(user_id, connection, credential, seconds=15) as (gateway, remaining):
                values = gateway.list_models()
                remaining()
                values = [value.strip() for value in values if isinstance(value, str) and 0 < len(value.strip()) <= 200]
                values = list(dict.fromkeys(values))
                return {"models": values[:200], "truncated": len(values) > 200}
        except ApplicationError:
            raise
        except Exception as error:
            if getattr(error, "status_code", None) in (404, 405):
                raise setup_error("MODEL_LIST_UNAVAILABLE", "Model discovery is unavailable. Enter a model ID manually.", 422) from None
            normalized = model_gateway_error(error)
            raise setup_error(normalized.code, normalized.message, normalized.status_code) from None

    def test(self, user_id, payload):
        _, connection, credential, binding = self.prepare(user_id, payload)
        result = {"generation": {"status": "not_run"}, "structured": {"status": "not_run"},
                  "status": "failed",
                  "verification_token": None, "tested_at": utc_now_iso()}
        with self._gateway(user_id, connection, credential, seconds=30) as (gateway, remaining):
            for name, method in (("generation", gateway.probe_generation), ("structured", gateway.probe_structured)):
                started = self.clock()
                try:
                    remaining()
                    usage = method()
                    remaining()
                    result[name] = {"status": "passed", "latency_ms": max(0, round((self.clock() - started) * 1000)), "usage": usage or None}
                except Exception as error:
                    normalized = error if isinstance(error, ApplicationError) else model_gateway_error(error)
                    result[name] = {"status": "failed", "latency_ms": max(0, round((self.clock() - started) * 1000)),
                                    "error_code": normalized.code, "usage": None}
                    break
        if result["generation"]["status"] == result["structured"]["status"] == "passed":
            result["status"] = "success"
            result["verification_token"] = self.verification.issue(binding)
        return result
