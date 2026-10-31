"""Live-run admission: what must be true before a provider is ever constructed.

Offline scenarios prove control flow; they cannot produce real quality or performance
evidence. A live run therefore needs an admission record that is *computed*, not
declared by the manifest itself, and the order matters: nothing may reach the provider
factory until admission has passed.

This module is deliberately free of side effects: it has no network, no provider, no
credential access. It only decides.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Digests use the project's fingerprint format: sha256 hex.
_DIGEST = r"^[a-f0-9]{64}$"
_SHA = r"^[a-f0-9]{40}$"


class EvaluationBudget(BaseModel):
    """The three limits an approved batch must state before it may run.

    All three are strictly positive. A zero or negative budget is not a batch that
    runs zero work; it is a batch that was never approved, and admitting it would let
    an "approved" run make its first attempt before noticing.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    max_calls: int = Field(gt=0)
    max_tokens: int = Field(gt=0)
    max_seconds: int = Field(gt=0)


class AcceptanceManifest(BaseModel):
    """What an approved live batch claims about itself.

    The manifest is produced by an approved configuration. Its values are never trusted
    on their own: ``admit_live`` recomputes the same facts from local state and compares.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    code_sha: str
    diff_digest: str
    suite_digest: str
    connection_ref: str
    connection_fingerprint: str
    provider: str
    model: str
    protocol: str
    engine: str
    strategy: Literal["reference", "optimized"]
    phase: Literal["probe", "compare", "acceptance"]
    invariant_fingerprint: str
    treatment_fingerprint: str
    review_mode: str
    grounding_mode: str
    synthetic_only: Literal[True]
    repeat: int
    annotation_protocol_version: str
    budget: EvaluationBudget

    @model_validator(mode="after")
    def non_empty(self):
        for name in (
            "code_sha", "diff_digest", "suite_digest", "connection_ref",
            "connection_fingerprint", "provider", "model", "protocol", "engine",
            "invariant_fingerprint", "treatment_fingerprint", "review_mode",
            "grounding_mode", "annotation_protocol_version",
        ):
            if not getattr(self, name):
                raise ValueError(f"Acceptance manifest requires {name}")
        if not re.fullmatch(_SHA, self.code_sha):
            raise ValueError("code_sha must be a git sha")
        for name in ("diff_digest", "suite_digest", "connection_fingerprint",
                     "invariant_fingerprint", "treatment_fingerprint"):
            if not re.fullmatch(_DIGEST, getattr(self, name)):
                raise ValueError(f"{name} must be a sha256 hex digest")
        return self


@dataclass(frozen=True)
class ActualState:
    """The facts admission recomputes locally; it never reads them from the manifest."""

    code_sha: str
    diff_digest: str
    suite_digest: str
    connection_fingerprint: str
    provider: str
    model: str
    protocol: str
    engine: str
    review_mode: str
    grounding_mode: str
    invariant_fingerprint: str
    treatment_fingerprint: str
    scenario_count: int
    has_real_user_data: bool
    provider_registry: frozenset[str]
    protocol_registry: frozenset[str]
    engine_registry: frozenset[str]
    safety_mode_registry: frozenset[str]
    max_cases: int


@dataclass(frozen=True)
class Authorization:
    """An operator's explicit approval for one batch.

    It is constructed by the operator, not by the manifest: a self-declared boolean in
    the manifest would let a manifest authorize itself.
    """

    approved_by: str
    expires_at: float
    reference: str

    def expired(self, now: float | None = None) -> bool:
        return (now if now is not None else time.time()) >= self.expires_at


class AdmissionRejected(RuntimeError):
    """Admission refused. Raised before any provider exists."""


def admit_live(
    manifest: AcceptanceManifest,
    *,
    actual: ActualState,
    authorization: Authorization | None,
    now: float | None = None,
) -> None:
    """Raise ``AdmissionRejected`` unless the approved batch may run.

    Every check happens here, before the caller is allowed to build a provider, so a
    refused batch cannot reach the network even accidentally.
    """
    if authorization is None:
        raise AdmissionRejected("LIVE_NOT_AUTHORIZED")
    if authorization.expired(now):
        raise AdmissionRejected("AUTHORIZATION_EXPIRED")
    if actual.has_real_user_data:
        raise AdmissionRejected("REAL_DATA_PRESENT")
    if manifest.synthetic_only is not True:
        raise AdmissionRejected("NOT_SYNTHETIC")

    for name, registry in (
        ("provider", actual.provider_registry),
        ("protocol", actual.protocol_registry),
        ("engine", actual.engine_registry),
        ("review_mode", actual.safety_mode_registry),
        ("grounding_mode", actual.safety_mode_registry),
    ):
        value = getattr(manifest, name)
        if value not in registry:
            raise AdmissionRejected(f"UNKNOWN_{name.upper()}")

    for name in (
        "code_sha", "diff_digest", "suite_digest", "connection_fingerprint",
        "provider", "model", "protocol", "engine", "review_mode", "grounding_mode",
        "invariant_fingerprint", "treatment_fingerprint",
    ):
        if getattr(manifest, name) != getattr(actual, name):
            raise AdmissionRejected(f"MISMATCH_{name.upper()}")

    if actual.scenario_count * manifest.repeat > actual.max_cases:
        raise AdmissionRejected("BATCH_EXCEEDS_CASE_LIMIT")
