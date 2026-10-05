"""Decomposition contract for the safety gate.

The gate is split into three concerns with file-level boundaries: detection,
decision and presentation. These tests make the decomposition an assertion rather
than a claim — swapping one rule pack must not disturb the others.
"""
import pathlib
import re

import pytest

from backend.safety import gate
from backend.safety import pack as pack_loader


RULES_DIR = pathlib.Path(gate.__file__).parent
PACK_DIR = RULES_DIR.parent / "data" / "safety"


def _blocked(question, **kwargs):
    """Run the output gate and return the refusal it raises.

    A blocked draft is signalled by raising, which is the contract the workflow
    relies on; only a shipped draft is returned.
    """
    with pytest.raises(gate.SafetyRefusal) as raised:
        gate.review_output(question, question, **kwargs)
    return raised.value


# --------------------------------------------------------------------------
# Pack loading
# --------------------------------------------------------------------------

def test_pack_loads_and_is_versioned():
    loaded = pack_loader.load_pack()

    assert loaded.pack_version
    assert loaded.locale
    assert loaded.concerns, "the pack must declare at least one concern"
    assert loaded.cues.negation, "the pack must declare negation cues"
    assert loaded.cues.pseudo, "pseudo-negation traps prevent false positives"
    assert loaded.policy.rules, "the pack must declare policy rules"


def test_domains_are_named_and_not_free_text():
    """Concerns are grouped by analysis domain, not by an invented metaphor."""
    loaded = pack_loader.load_pack()

    domains = {concern.domain for concern in loaded.concerns}
    assert domains <= {"nutrition", "training", "shared"}
    assert "nutrition" in domains


def test_pack_rejects_an_unknown_schema_version(tmp_path):
    bad = tmp_path / "concerns.yaml"
    bad.write_text("schema_version: 99\nconcerns: []\n", encoding="utf-8")

    with pytest.raises(ValueError):
        pack_loader.load_concerns(bad)


def test_pack_rejects_duplicate_surface_terms_across_concerns(tmp_path):
    bad = tmp_path / "concerns.yaml"
    bad.write_text(
        "schema_version: 1\npack_version: '1.0.0'\nlocale: zh-CN\nconcerns:\n"
        "  - id: a\n    domain: nutrition\n    surface: ['诊断']\n    default_severity: 2\n"
        "  - id: b\n    domain: training\n    surface: ['诊断']\n    default_severity: 3\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        pack_loader.load_concerns(bad)


def test_pack_rejects_an_out_of_range_severity(tmp_path):
    bad = tmp_path / "concerns.yaml"
    bad.write_text(
        "schema_version: 1\npack_version: '1.0.0'\nlocale: zh-CN\nconcerns:\n"
        "  - id: a\n    domain: nutrition\n    surface: ['诊断']\n    default_severity: 99\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        pack_loader.load_concerns(bad)


def test_policy_rejects_an_unknown_action(tmp_path):
    bad = tmp_path / "policy.yaml"
    bad.write_text(
        "schema_version: 1\npack_version: '1.0.0'\ndefault_action: allow\nrules:\n"
        "  - when: {concern: a}\n    action: obliterate\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        pack_loader.load_policy(bad)


# --------------------------------------------------------------------------
# Detection knows Chinese; the engine does not
# --------------------------------------------------------------------------

def test_no_risk_term_is_hardcoded_in_the_engine():
    """The engine handles concerns; the pack lists them.

    If a concern *identifier* appears in engine code, detection and rule content
    have been re-coupled.
    """
    loaded = pack_loader.load_pack()
    engine_files = [
        path
        for path in sorted(RULES_DIR.glob("*.py"))
        if path.name not in {"__init__.py", "pack.py"}
    ]
    engine_code = "\n".join(_code_only(path) for path in engine_files)

    leaks = [concern.id for concern in loaded.concerns if concern.id in engine_code]
    assert not leaks, f"concern identifiers leaked into engine code: {leaks}"
    assert engine_code.strip(), "sanity: engine code was actually read"


def _code_only(path: pathlib.Path) -> str:
    """Source with comments and string literals removed.

    A term in a comment or docstring is documentation, not coupling. Only a term
    in executable code means the engine has absorbed a rule.
    """
    import io
    import tokenize

    pieces: list[str] = []
    with path.open("rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type in {tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE}:
                continue
            pieces.append(token.string)
    return " ".join(pieces)


def test_engine_source_contains_no_pack_surface_terms():
    """A term embedded in engine *code* would re-couple rules to detection.

    Latin terms are matched on word boundaries: a short English term such as
    "inject" otherwise matches inside an unrelated word or comment.
    """
    loaded = pack_loader.load_pack()
    terms = [term for concern in loaded.concerns for term in concern.surface]
    assert terms, "pack declares no surface terms"

    engine_files = [
        path
        for path in sorted(RULES_DIR.glob("*.py"))
        if path.name not in {"__init__.py", "pack.py"}
    ]
    engine_code = "\n".join(_code_only(path) for path in engine_files)

    found: list[str] = []
    for term in terms:
        if term.isascii():
            if re.search(rf"\b{re.escape(term)}\b", engine_code, re.IGNORECASE):
                found.append(term)
        elif term in engine_code:
            found.append(term)
    assert not found, f"surface terms embedded in engine code: {found}"


# --------------------------------------------------------------------------
# Detection and presentation are separable
# --------------------------------------------------------------------------

def test_swapping_notices_does_not_change_the_verdict():
    question = "我该吃什么药来治疗糖尿病"

    original = _blocked(question)
    swapped = _blocked(
        question,
        messages=pack_loader.Messages(locale="zh-CN", notices={"*": "完全不同的一段话"}),
    )

    assert swapped.verdict.action == original.verdict.action
    assert swapped.verdict.severity == original.verdict.severity
    assert swapped.verdict.modifiers == original.verdict.modifiers
    assert swapped.verdict.concern == original.verdict.concern
    assert str(swapped) != str(original)
    assert "完全不同的一段话" in str(swapped)


def test_swapping_policy_does_not_change_notice_rendering():
    question = "我该吃什么药来治疗糖尿病"
    permissive = pack_loader.Policy(default_action="allow", rules=())

    strict = _blocked(question)
    # A permissive policy ships the text unchanged, so no refusal is raised.
    relaxed = gate.review_output(question, question, policy=permissive)

    assert strict.verdict.action == "refuse"
    assert relaxed.verdict.action == "allow"
    assert relaxed.text == question
    assert relaxed.notice is None


def test_severity_policy_change_is_independent_of_concern_content():
    """The same concern, a different policy row, a different action."""
    question = "我该吃什么药来治疗糖尿病"

    base = _blocked(question)
    assert base.verdict.concern == "clinical_territory"
    assert base.verdict.action == "refuse"

    clinical_only = pack_loader.Policy(
        default_action="allow",
        rules=(
            pack_loader.PolicyRule(
                when={"concern": "clinical_territory"},
                action="disclose",
                notice="clinical_boundary",
            ),
        ),
    )
    changed = gate.review_output(question, question, policy=clinical_only)

    assert changed.verdict.concern == base.verdict.concern
    assert changed.verdict.action == "disclose"
    assert changed.text.startswith(question)
    assert "clinical_boundary" not in changed.text  # the notice key is not the text
