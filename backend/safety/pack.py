"""Strict loading of the safety rule packs.

The packs are versioned assets committed with the application — not runtime
configuration. They are never read from environment variables, an admin endpoint
or a request. A malformed, missing or unsupported pack raises, so a broken rule
pack stops the application instead of silently weakening the gate.
"""
from __future__ import annotations

import pathlib
from typing import Any

import yaml

from backend.safety.models import (
    CUE_CLASSES,
    KNOWN_DOMAINS,
    MAX_SEVERITY,
    MIN_SEVERITY,
    Concern,
    CueTables,
    Messages,
    Policy,
    PolicyRule,
    RulePack,
)
from backend.safety.policy import validate_policy, validate_policy_for_position


DEFAULT_PACK_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "safety"
SUPPORTED_SCHEMA_VERSION = 1


def _read_yaml(path: pathlib.Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Safety rule pack is missing: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Safety rule pack must be a mapping: {path}")
    version = payload.get("schema_version")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise ValueError(f"Unsupported safety pack schema version: {version!r}")
    return payload


def _text_tuple(values: Any, *, field: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, list):
        raise ValueError(f"{field} must be a list")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} entries must be non-empty strings")
        result.append(value.strip())
    return tuple(result)


def load_concerns(path: pathlib.Path | None = None) -> tuple[Concern, ...]:
    payload = _read_yaml(path or DEFAULT_PACK_DIR / "concerns.zh-CN.v1.yaml")
    raw = payload.get("concerns")
    if not isinstance(raw, list) or not raw:
        raise ValueError("A safety pack must declare at least one concern")

    concerns: list[Concern] = []
    seen_ids: set[str] = set()
    seen_terms: dict[str, str] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("Each concern must be a mapping")
        concern_id = entry.get("id")
        domain = entry.get("domain")
        if not isinstance(concern_id, str) or not concern_id:
            raise ValueError("A concern needs an id")
        if concern_id in seen_ids:
            raise ValueError(f"Duplicate concern id: {concern_id}")
        if domain not in KNOWN_DOMAINS:
            raise ValueError(f"Unknown analysis domain for concern {concern_id}: {domain!r}")
        severity = entry.get("default_severity")
        if not isinstance(severity, int) or isinstance(severity, bool):
            raise ValueError(f"Concern {concern_id} needs an integer default_severity")
        if not MIN_SEVERITY <= severity <= MAX_SEVERITY:
            raise ValueError(f"Concern {concern_id} severity out of range: {severity}")
        surface = _text_tuple(entry.get("surface"), field=f"{concern_id}.surface")
        if not surface:
            raise ValueError(f"Concern {concern_id} declares no surface terms")
        for term in surface:
            folded = term.lower()
            if folded in seen_terms:
                raise ValueError(
                    f"Surface term {term!r} is declared by both "
                    f"{seen_terms[folded]} and {concern_id}"
                )
            seen_terms[folded] = concern_id
        seen_ids.add(concern_id)
        concerns.append(
            Concern(
                id=concern_id,
                domain=domain,
                surface=surface,
                default_severity=severity,
                title=str(entry.get("title", "")),
            )
        )
    return tuple(concerns)


def load_cues(path: pathlib.Path | None = None) -> CueTables:
    payload = _read_yaml(path or DEFAULT_PACK_DIR / "triggers.zh.v1.yaml")
    raw = payload.get("cues")
    if not isinstance(raw, dict):
        raise ValueError("A cue pack must declare a `cues` mapping")
    unknown = set(raw) - set(CUE_CLASSES)
    if unknown:
        raise ValueError(f"Unknown cue class: {sorted(unknown)}")
    values = {name: _text_tuple(raw.get(name), field=f"cues.{name}") for name in CUE_CLASSES}
    if not values["negation"]:
        raise ValueError("A cue pack must declare negation cues")
    if not values["pseudo"]:
        raise ValueError(
            "A cue pack must declare pseudo-negation traps; without them "
            "phrases such as 不仅 register as negations"
        )
    return CueTables(
        **values,
        third_party=_text_tuple(payload.get("third_party"), field="third_party"),
        definitional_markers=_text_tuple(
            payload.get("definitional_markers"), field="definitional_markers"
        ),
        imperative_markers=_text_tuple(
            payload.get("imperative_markers"), field="imperative_markers"
        ),
        jailbreak_patterns=_load_jailbreak_patterns(payload.get("jailbreak_patterns")),
    )


def _load_jailbreak_patterns(raw: Any) -> dict[str, tuple[str, ...]]:
    """Manipulation patterns, keyed by pattern id.

    Requiring a mapping (rather than one flat phrase list) keeps the reason for each
    match reportable, which is what makes an escalated decision reviewable.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("jailbreak_patterns must be a mapping of pattern id to phrases")
    patterns: dict[str, tuple[str, ...]] = {}
    for pattern_id, phrases in raw.items():
        if not isinstance(pattern_id, str) or not pattern_id:
            raise ValueError("A jailbreak pattern needs a string id")
        values = _text_tuple(phrases, field=f"jailbreak_patterns.{pattern_id}")
        if not values:
            raise ValueError(f"Jailbreak pattern {pattern_id} declares no phrases")
        patterns[pattern_id] = values
    return patterns


def load_policy(path: pathlib.Path | None = None) -> Policy:
    payload = _read_yaml(path or DEFAULT_PACK_DIR / "policy.v1.yaml")
    raw = payload.get("rules", [])
    if not isinstance(raw, list):
        raise ValueError("policy.rules must be a list")
    rules: list[PolicyRule] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("Each policy rule must be a mapping")
        when = entry.get("when")
        if not isinstance(when, dict):
            raise ValueError("Each policy rule needs a `when` mapping")
        action = entry.get("action")
        if not isinstance(action, str):
            raise ValueError("Each policy rule needs a string action")
        notice = entry.get("notice")
        if notice is not None and not isinstance(notice, str):
            raise ValueError("A policy notice must be a string")
        rules.append(PolicyRule(when=dict(when), action=action, notice=notice))
    policy = Policy(default_action=payload.get("default_action", "allow"), rules=tuple(rules))
    validate_policy(policy)
    return policy


def load_messages(path: pathlib.Path | None = None) -> Messages:
    payload = _read_yaml(path or DEFAULT_PACK_DIR / "messages.zh-CN.v1.yaml")
    raw = payload.get("notices")
    if not isinstance(raw, dict) or not raw:
        raise ValueError("A message pack must declare notices")
    notices: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value.strip():
            raise ValueError("Notices must map non-empty strings to non-empty strings")
        notices[key] = value
    return Messages(locale=str(payload.get("locale", "")), notices=notices)


def load_pack(directory: pathlib.Path | None = None) -> RulePack:
    """Load and cross-validate every pack, or raise."""
    base = directory or DEFAULT_PACK_DIR
    concerns_path = base / "concerns.zh-CN.v1.yaml"
    cues_path = base / "triggers.zh.v1.yaml"
    policy_path = base / "policy.v1.yaml"
    messages_path = base / "messages.zh-CN.v1.yaml"

    concerns = load_concerns(concerns_path)
    cues = load_cues(cues_path)
    policy = load_policy(policy_path)
    messages = load_messages(messages_path)
    payload = _read_yaml(concerns_path)

    known = {concern.id for concern in concerns}
    for rule in policy.rules:
        referenced = rule.when.get("concern")
        if referenced is not None and referenced not in known:
            raise ValueError(f"Policy references an unknown concern: {referenced}")
    for rule in policy.rules:
        if rule.notice is not None and rule.notice not in messages.notices:
            raise ValueError(f"Policy references an unknown notice: {rule.notice}")
    # An action that cannot mean anything at a position is a configuration error, and
    # it is caught here rather than surfacing as a confusing runtime result.
    validate_policy_for_position(policy, position="input")
    validate_policy_for_position(policy, position="output")

    return RulePack(
        schema_version=SUPPORTED_SCHEMA_VERSION,
        pack_version=str(payload.get("pack_version", "")),
        locale=str(payload.get("locale", "")),
        concerns=concerns,
        cues=cues,
        policy=policy,
        messages=messages,
    )
