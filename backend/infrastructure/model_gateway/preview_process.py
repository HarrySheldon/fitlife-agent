"""Killable settings probes, not a durable task queue or a business Agent runner.

Only resolved connection fields and the selected credential cross the private
spawn pipe. No user directory, settings file, task state or health data is read.
"""
import json
import logging
import multiprocessing
import os
import sys
import time

from backend.application.ports.model_call_context import remaining_model_timeout
from backend.domain.errors import ApplicationError, model_gateway_error
from backend.domain.model_connection import ModelConnection


MAX_MESSAGE_BYTES = 256 * 1024
OPERATIONS = {"models": "list_models", "generation": "probe_generation", "structured": "probe_structured"}


def _probe_worker(channel, payload):
    gateway = None
    # Provider SDK diagnostics must never echo credentials into server logs.
    sys.stdout = open(os.devnull, "w")
    sys.stderr = sys.stdout
    os.environ.pop("OPENAI_LOG", None)
    logging.disable(logging.CRITICAL)
    try:
        from backend.infrastructure.model_gateway.factory import create_model_gateway

        connection = ModelConnection.model_validate(payload["connection"])
        gateway = create_model_gateway(connection, payload["credential"])
        value = getattr(gateway, OPERATIONS[payload["operation"]])()
        if payload["operation"] == "models":
            value = [item for item in value if isinstance(item, str) and 0 < len(item) <= 200][:201]
        message = {"ok": True, "value": value}
    except Exception as error:
        normalized = error if isinstance(error, ApplicationError) else model_gateway_error(error)
        if payload.get("operation") == "models" and getattr(error, "status_code", None) in (404, 405):
            message = {"ok": False, "code": "MODEL_LIST_UNAVAILABLE", "status": 422}
        else:
            message = {"ok": False, "code": normalized.code, "status": normalized.status_code}
    try:
        try:
            data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (ValueError, TypeError):
            data = b'{"ok":false,"code":"MODEL_PROTOCOL_ERROR","status":502}'
        if len(data) > MAX_MESSAGE_BYTES:
            data = b'{"ok":false,"code":"MODEL_PROTOCOL_ERROR","status":502}'
        try:
            channel.send_bytes(data)
        except OSError:
            pass  # The parent may have already enforced its deadline.
    finally:
        if gateway is not None:
            try:
                gateway.close()
            except Exception:
                pass
        channel.close()


class ProbeProcessRunner:
    def __init__(self, *, worker=_probe_worker):
        self.worker = worker

    def run(self, payload: dict, *, seconds: float):
        if seconds <= 0:
            raise TimeoutError("Probe deadline reached")
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=self.worker, args=(sender, payload), daemon=True)
        started = False
        deadline = time.monotonic() + seconds
        try:
            process.start()
            started = True
            sender.close()
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not receiver.poll(remaining):
                raise TimeoutError("Probe deadline reached")
            message = json.loads(receiver.recv_bytes(MAX_MESSAGE_BYTES))
            if time.monotonic() >= deadline:
                raise TimeoutError("Probe deadline reached")
            if not isinstance(message, dict) or message.get("ok") is not True:
                code = message.get("code") if isinstance(message, dict) else None
                if code == "MODEL_TIMEOUT":
                    raise TimeoutError("Probe deadline reached")
                status = message.get("status", 502) if isinstance(message, dict) else 502
                if code not in {"MODEL_AUTH_FAILED", "MODEL_NOT_FOUND", "MODEL_QUOTA_EXHAUSTED",
                    "MODEL_RATE_LIMITED", "MODEL_LIST_UNAVAILABLE", "INVALID_MODEL_ENDPOINT"}:
                    code, status = "MODEL_PROTOCOL_ERROR", 502
                raise ApplicationError(code=code, message="The model connection check failed.", status_code=status)
            return message.get("value")
        except TimeoutError:
            raise
        except (EOFError, OSError, ValueError):
            raise ApplicationError(code="MODEL_PROTOCOL_ERROR", message="The model connection check failed.", status_code=502) from None
        finally:
            receiver.close()
            sender.close()
            if started:
                process.join(timeout=0.05)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=0.1)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=0.1)
                if not process.is_alive():
                    process.close()
            else:
                process.close()


class PreviewProcessGateway:
    def __init__(self, connection: ModelConnection, credential: str, *, runner=None):
        self.model = connection.model
        self._connection = connection.model_dump(mode="json", include={"provider_id", "provider", "protocol", "base_url", "model"})
        self._credential = credential
        self._runner = runner or ProbeProcessRunner()

    def _run(self, operation, maximum):
        if self._credential is None:
            raise RuntimeError("The preview gateway is closed")
        remaining = remaining_model_timeout.get()
        seconds = min(maximum, remaining()) if remaining else maximum
        return self._runner.run({"connection": self._connection, "credential": self._credential,
            "operation": operation}, seconds=seconds)

    def list_models(self):
        return self._run("models", 15.0)

    def probe_generation(self):
        return self._run("generation", 30.0)

    def probe_structured(self):
        return self._run("structured", 30.0)

    def close(self):
        self._credential = None


def create_preview_gateway(connection: ModelConnection, credential: str):
    return PreviewProcessGateway(connection, credential)
