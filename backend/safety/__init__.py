"""The safety gate, split into detection, decision and presentation.

- :mod:`backend.safety.gate` is the only module consumers should import.
- ``models``/``normalize``/``match``/``scope``/``policy`` are the engine. They
  contain no domain vocabulary: risk terms, cues, thresholds and wording all come
  from the versioned packs under ``backend/data/safety/``.
- :mod:`backend.safety.pack` loads those packs strictly and fails closed.
"""
from backend.safety.gate import (
    MAX_QUESTION_CHARS,
    SAFETY_RULE_VERSION,
    ReviewResult,
    SafetyRefusal,
    check_input,
    default_pack,
    review_output,
)
from backend.safety.models import Modifier, Policy, Verdict

__all__ = [
    "MAX_QUESTION_CHARS",
    "SAFETY_RULE_VERSION",
    "Modifier",
    "Policy",
    "ReviewResult",
    "SafetyRefusal",
    "Verdict",
    "check_input",
    "default_pack",
    "review_output",
]
