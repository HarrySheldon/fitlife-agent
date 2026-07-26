import pytest

from backend.domain.smart_entry import (
    SmartEntryDomainError,
    parse_entry_text,
    validate_agent_patch,
)


def test_parse_entry_text_keeps_only_explicit_food_and_workout_values():
    parsed = parse_entry_text(
        "早餐：燕麦 50g，牛奶 250ml\n"
        "力量：深蹲 3x8 60kg\n"
        "有氧：跑步 30分钟，设备消耗 280千卡"
    )

    assert [segment.kind for segment in parsed.segments] == [
        "food",
        "food",
        "strength",
        "cardio",
    ]
    assert parsed.segments[0].meal_context == "breakfast"
    assert parsed.segments[0].food_amount == 50
    assert parsed.segments[0].food_unit == "g"
    assert parsed.segments[1].food_amount == 250
    assert parsed.segments[1].food_unit == "ml"
    assert parsed.segments[2].set_count == 3
    assert parsed.segments[2].reps == 8
    assert parsed.segments[2].load_kg == 60
    assert parsed.segments[3].duration_min == 30
    assert parsed.segments[3].device_calories == 280


def test_candidate_ids_are_stable_across_width_case_and_spacing():
    first = parse_entry_text("BREAKFAST: Oats 50g")
    second = parse_entry_text("ｂｒｅａｋｆａｓｔ：  oats   50g")

    assert first.segments[0].id == second.segments[0].id
    assert second.segments[0].raw_text == "oats   50g"


def test_parse_chinese_and_english_strength_volume_and_bodyweight():
    parsed = parse_entry_text(
        "力量：俯卧撑 4组 每组12次 自重；"
        "Strength: Pull-up 3 sets of 6 bodyweight"
    )

    assert [
        (item.set_count, item.reps, item.bodyweight)
        for item in parsed.segments
    ] == [(4, 12, True), (3, 6, True)]


def test_partial_and_unknown_segments_keep_coded_issues():
    parsed = parse_entry_text("早餐：燕麦；力量：深蹲；随便来一点")

    assert [item.kind for item in parsed.segments] == [
        "food",
        "strength",
        "unknown",
    ]
    assert [item.issues for item in parsed.segments] == [
        ("SMART_ENTRY_FOOD_AMOUNT_REQUIRED",),
        ("SMART_ENTRY_STRENGTH_VOLUME_REQUIRED",),
        ("SMART_ENTRY_KIND_UNRESOLVED",),
    ]


@pytest.mark.parametrize(
    "field",
    [
        "set_count",
        "reps",
        "load_kg",
        "duration_min",
        "device_calories",
    ],
)
def test_agent_patch_cannot_add_observed_workout_values(field: str):
    segment = parse_entry_text("力量：深蹲 3x8 60kg").segments[0]

    with pytest.raises(SmartEntryDomainError) as raised:
        validate_agent_patch(segment, {field: 999})

    assert raised.value.code == "SMART_ENTRY_AGENT_OBSERVED_FIELD_FORBIDDEN"


def test_agent_patch_can_only_fill_bounded_analysis_fields():
    segment = parse_entry_text("早餐：燕麦 50g").segments[0]

    patch = validate_agent_patch(
        segment,
        {
            "canonical_name": "燕麦",
            "calories": 190,
            "assumptions": ["按干燕麦估算"],
        },
    )

    assert patch["calories"] == 190
    with pytest.raises(SmartEntryDomainError) as raised:
        validate_agent_patch(segment, {"admin": True})
    assert raised.value.code == "SMART_ENTRY_AGENT_PATCH_FIELD_FORBIDDEN"
