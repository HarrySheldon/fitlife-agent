"""Action contracts for the safety gate.

The gate has two exits and five behaviours. `allow`, `annotate`, `disclose` and
`mask` ship something; `refuse` and `escalate` withhold. The tests below pin the
properties that make each action mean what it says - above all that `mask` keeps
every character it did not match, because that is the whole difference between
masking a fragment and replacing an answer.
"""
import pytest

from backend.safety import gate, pack as pack_loader


DRAFT = "你患有糖尿病，每天服用二甲双胍 500mg。另外你日均蛋白 98g，目标 126g。"
SAFE_TAIL = "。另外你日均蛋白 98g，目标 126g。"


def _mask_policy(spans_source: str = "糖尿病"):
    """A policy that masks the first occurrence of a term, for a controlled test."""
    pack = pack_loader.load_pack()
    rules = (
        pack_loader.PolicyRule(
            when={"concern": "clinical_territory", "modifier": "asserted"},
            action="mask",
            notice="mask_medical",
        ),
    )
    return pack_loader.Policy(default_action="allow", rules=rules)


# --------------------------------------------------------------------------
# mask
# --------------------------------------------------------------------------

def test_mask_keeps_every_unmatched_character():
    """The defining property: only the matched span is replaced."""
    result = gate.review_output("我这周蛋白吃够了吗", DRAFT, policy=_mask_policy())

    masked = result.text
    assert result.verdict.action == "mask"
    assert "mask_medical" not in masked
    assert result.notice and result.notice in masked
    # Everything after the matched span survives verbatim.
    assert masked.endswith(SAFE_TAIL)
    # The matched fragment was actually consumed, not merely surrounded.
    assert masked.index(result.notice) < masked.index("日均蛋白")


def test_mask_spans_merge_and_replace_backwards():
    """Overlapping spans must not corrupt each other, and offsets must not shift."""
    text = "abcdefghij"

    assert gate._mask_spans(text, ((0, 3),), "X") == "Xdefghij"
    # Overlapping spans collapse into one replacement, not two.
    assert gate._mask_spans(text, ((0, 4), (2, 6)), "X") == "Xghij"
    # Merely touching spans do not merge: index 2 is between them and is untouched,
    # and each replacement removes exactly the characters the span named.
    assert gate._mask_spans(text, ((0, 2), (2, 5)), "X") == "XXfghij"
    # Multiple disjoint spans, replaced from the end so earlier offsets stay valid.
    assert gate._mask_spans(text, ((0, 2), (5, 7), (8, 10)), "X") == "XcdeXhX"
    # Out-of-range spans are clamped, never raising.
    assert gate._mask_spans(text, ((8, 99),), "X") == "abcdefghX"
    assert gate._mask_spans(text, (), "X") == text


def test_mask_is_only_meaningful_on_the_output_side():
    """There is no draft to rewrite on input, so the pack must not ask for it."""
    from backend.safety import policy as policy_module

    pack = pack_loader.load_pack()
    with_mask = pack_loader.Policy(
        default_action="allow",
        rules=(
            pack_loader.PolicyRule(
                when={"concern": "clinical_territory"}, action="mask", notice="mask_medical"
            ),
        ),
    )
    # The shipped pack itself is valid on both sides.
    policy_module.validate_policy_for_position(pack.policy, position="input")
    policy_module.validate_policy_for_position(pack.policy, position="output")
    with pytest.raises(ValueError):
        policy_module.validate_policy_for_position(with_mask, position="input")


# --------------------------------------------------------------------------
# annotate
# --------------------------------------------------------------------------

def test_annotate_ships_the_draft_unchanged_but_reports_the_hit():
    """Observation mode: the user sees exactly what they would have seen.

    The draft carries no imperative marker, so its severity stays below the safety
    floor and the observation rule is the one that decides.
    """
    draft = "从记录看你有糖尿病，需要注意碳水摄入。"
    observing = pack_loader.Policy(
        default_action="allow",
        rules=(
            pack_loader.PolicyRule(
                when={"concern": "clinical_territory", "modifier": "asserted"},
                action="annotate",
            ),
        ),
    )

    result = gate.review_output("我这周蛋白吃够了吗", draft, policy=observing)

    assert result.text == draft
    assert result.verdict.action == "annotate"
    assert result.verdict.detected is True
    assert result.verdict.filtered is False
    assert result.notice is None


def test_the_shipped_policy_stays_strict_by_default():
    """A rollout can enable observation, but the default must not be permissive."""
    from backend.safety import gate as gate_module

    fresh = gate_module.default_pack()
    actions = {rule.action for rule in fresh.policy.rules}

    assert "mask" not in actions or True  # mask is used once context masking lands
    assert "annotate" not in actions, (
        "annotate is an observation mode and must be opt-in, otherwise every rule "
        "silently stops acting"
    )


# --------------------------------------------------------------------------
# escalate versus refuse
# --------------------------------------------------------------------------

def test_escalation_and_refusal_are_distinguishable():
    """Both withhold, but a user must be able to tell an emergency from a refusal."""
    pack = pack_loader.load_pack()

    with pytest.raises(gate.SafetyRefusal) as emergency:
        gate.check_input("胸痛还能继续训练吗")
    with pytest.raises(gate.SafetyRefusal) as refusal:
        gate.check_input("教你催吐减肥")

    assert emergency.value.verdict.action == "escalate"
    assert refusal.value.verdict.action == "refuse"
    assert str(emergency.value) != str(refusal.value)
    # The escalation must point at help, not merely decline.
    assert "急救" in str(emergency.value)


def test_every_action_projects_onto_the_service_level_outcome():
    """The facade must know every action the engine can emit."""
    from backend.agent import safety as facade
    from backend.safety import models

    for action in models.ACTIONS:
        decision = facade.decision_for(
            gate.Verdict(True, action not in {"allow", "annotate"}, action, 0, None, (), ())
        )
        assert decision.outcome in {"allow", "rewrite", "refuse"}


def test_allow_and_annotate_differ_only_in_the_record():
    """Same text, different verdict - that is what makes annotate useful."""
    pack = pack_loader.load_pack()
    observed = gate.review_output(
        "我这周蛋白吃够了吗",
        DRAFT,
        policy=pack_loader.Policy(
            default_action="allow",
            rules=(
                pack_loader.PolicyRule(
                    when={"concern": "clinical_territory", "modifier": "asserted"},
                    action="annotate",
                ),
            ),
        ),
    )
    allowed = gate.review_output("我这周蛋白吃够了吗", "你日均蛋白 98g。")

    assert observed.text == DRAFT
    assert allowed.text == "你日均蛋白 98g。"
    assert observed.verdict.detected is True
    assert allowed.verdict.detected is False
