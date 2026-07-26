import json
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from backend.agent.smart_entry_analyzer import (
    FoodAnalysisSuggestion,
    NumericEstimate,
    PROMPT_VERSION,
    SmartEntryAnalysisResponse,
    analyze_smart_entry,
)
from backend.application.ports.smart_entry_repository import (
    SmartEntryDraft,
    SmartEntryDraftPayload,
    SmartEntryRepositoryError,
)
from backend.application.ports.structured_model_gateway import (
    StructuredModelResult,
)
from backend.domain.smart_entry import ResolvedCandidate
from backend.application.use_cases.smart_entry import SmartEntryService
from backend.domain.errors import ApplicationError


def _candidate() -> ResolvedCandidate:
    return ResolvedCandidate(
        id="segment-food",
        kind="food",
        raw_text="自制饭团 1份",
        normalized_text="自制饭团 1份",
        subject_text="自制饭团",
        meal_context="lunch",
        selected=True,
        selected_catalog_id=None,
        catalog_choices=(),
        issues=("SMART_ENTRY_CATALOG_UNMATCHED",),
        values={"amount": 1, "unit": "serving"},
        provenance={},
    )


def test_smart_entry_analysis_schema_rejects_observed_workout_fields():
    with pytest.raises(ValidationError):
        SmartEntryAnalysisResponse.model_validate(
            {
                "food_suggestions": [],
                "exercise_suggestions": [
                    {
                        "candidate_id": "strength-1",
                        "canonical_name": "深蹲",
                        "exercise_type": "strength",
                        "primary_muscle": "quadriceps",
                        "secondary_muscles": [],
                        "met": None,
                        "assumptions": [],
                        "sets": 5,
                    }
                ],
            }
        )


def test_analyzer_sends_only_unresolved_candidates_and_minimum_profile():
    gateway = Mock()
    output = SmartEntryAnalysisResponse()
    gateway.parse_structured.return_value = StructuredModelResult(
        output=output,
        model="gpt-test",
        usage={"total_tokens": 20},
    )
    resolved = ResolvedCandidate(
        **{
            **_candidate().__dict__,
            "id": "resolved",
            "issues": (),
        }
    )

    result = analyze_smart_entry(
        gateway,
        (_candidate(), resolved),
        locale="zh-CN",
        weight_kg=70,
    )

    assert result.output is output
    call = gateway.parse_structured.call_args.kwargs
    request = json.loads(call["input_text"])
    assert PROMPT_VERSION == "smart-entry-analysis-v1"
    assert request["profile"] == {"weight_kg": 70}
    assert [item["id"] for item in request["candidates"]] == ["segment-food"]
    assert "set_count" not in request["candidates"][0]["explicit_values"]


def _draft() -> SmartEntryDraft:
    return SmartEntryDraft(
        id="draft-1",
        user_id="user-1",
        payload=SmartEntryDraftPayload(
            log_date="2026-07-26",
            raw_text="自制饭团 1份",
            parser_version="smart-entry-parser-v1",
            candidates=(_candidate(),),
        ),
        version=3,
        agent_status="not_requested",
        agent_prompt_version=None,
        agent_model=None,
        agent_metadata={},
        expires_at="2026-08-25T00:00:00Z",
        created_at="2026-07-26T00:00:00Z",
        updated_at="2026-07-26T00:00:00Z",
    )


def _estimate(value: float) -> NumericEstimate:
    return NumericEstimate(
        value=value,
        min_value=value * 0.8,
        max_value=value * 1.2,
        basis="typical prepared serving",
    )


def test_service_merges_agent_estimates_without_formal_writes():
    repository = Mock()
    repository.get_draft.return_value = _draft()
    repository.save_analysis.return_value = Mock(spec=SmartEntryDraft)
    gateway = Mock()
    gateway.model = "configured-model"
    gateway.parse_structured.return_value = StructuredModelResult(
        output=SmartEntryAnalysisResponse(
            food_suggestions=(
                FoodAnalysisSuggestion(
                    candidate_id="segment-food",
                    canonical_name="自制饭团",
                    calories=_estimate(240),
                    carbs=_estimate(42),
                    protein=_estimate(7),
                    fat=_estimate(5),
                    serving_assumption="one medium rice ball",
                    assumptions=("rice-based filling",),
                ),
            )
        ),
        model="resolved-model",
        usage={"total_tokens": 80},
    )
    service = SmartEntryService(
        repository,
        Mock(),
        Mock(),
        gateway_resolver=lambda _user_id: gateway,
    )

    result = service.analyze_draft(
        "user-1",
        "draft-1",
        expected_version=3,
        locale="zh-CN",
        weight_kg=70,
    )

    assert result is repository.save_analysis.return_value
    call = repository.save_analysis.call_args.kwargs
    candidate = call["payload"].candidates[0]
    assert candidate.values["calories"] == 240
    assert candidate.values["amount"] == 1
    assert candidate.values["source"] == "agent_estimate"
    assert candidate.agent_estimate_accepted is False
    assert candidate.issues == (
        "SMART_ENTRY_AGENT_ESTIMATE_ACCEPTANCE_REQUIRED",
    )
    assert call["expected_version"] == 3
    assert call["metadata"] == {"usage": {"total_tokens": 80}}


def test_service_preserves_draft_and_marks_normalized_model_failure():
    repository = Mock()
    repository.get_draft.return_value = _draft()
    gateway = Mock()
    gateway.model = "configured-model"
    gateway.parse_structured.side_effect = TimeoutError()
    service = SmartEntryService(
        repository,
        Mock(),
        Mock(),
        gateway_resolver=lambda _user_id: gateway,
    )

    with pytest.raises(ApplicationError) as raised:
        service.analyze_draft(
            "user-1",
            "draft-1",
            expected_version=3,
            locale="zh-CN",
            weight_kg=None,
        )

    assert raised.value.code == "MODEL_TIMEOUT"
    repository.mark_agent_failed.assert_called_once_with(
        "user-1",
        "draft-1",
        expected_version=3,
        prompt_version=PROMPT_VERSION,
        model="configured-model",
        metadata={"error_code": "MODEL_TIMEOUT"},
    )
    repository.save_analysis.assert_not_called()


def test_service_discards_stale_agent_result_with_conflict():
    repository = Mock()
    repository.get_draft.return_value = _draft()
    repository.save_analysis.side_effect = SmartEntryRepositoryError(
        "DRAFT_VERSION_CONFLICT"
    )
    gateway = Mock()
    gateway.model = "configured-model"
    gateway.parse_structured.return_value = StructuredModelResult(
        output=SmartEntryAnalysisResponse(),
        model="configured-model",
        usage={},
    )
    service = SmartEntryService(
        repository,
        Mock(),
        Mock(),
        gateway_resolver=lambda _user_id: gateway,
    )

    with pytest.raises(ApplicationError) as raised:
        service.analyze_draft(
            "user-1",
            "draft-1",
            expected_version=3,
            locale="en",
            weight_kg=None,
        )

    assert raised.value.code == "DRAFT_VERSION_CONFLICT"
    assert raised.value.status_code == 409
    assert raised.value.processing_mode == "agent"


@pytest.mark.parametrize(
    ("error_type", "expected_code"),
    [
        (type("AuthenticationError", (Exception,), {}), "MODEL_AUTH_FAILED"),
        (type("RateLimitError", (Exception,), {}), "MODEL_RATE_LIMITED"),
        (ValueError, "MODEL_PROTOCOL_ERROR"),
    ],
)
def test_service_normalizes_provider_and_structure_failures(
    error_type,
    expected_code,
):
    repository = Mock()
    repository.get_draft.return_value = _draft()
    gateway = Mock()
    gateway.model = "configured-model"
    gateway.parse_structured.side_effect = error_type()
    service = SmartEntryService(
        repository,
        Mock(),
        Mock(),
        gateway_resolver=lambda _user_id: gateway,
    )

    with pytest.raises(ApplicationError) as raised:
        service.analyze_draft(
            "user-1",
            "draft-1",
            expected_version=3,
            locale="zh-CN",
            weight_kg=None,
        )

    assert raised.value.code == expected_code
    assert repository.mark_agent_failed.call_args.kwargs["metadata"] == {
        "error_code": expected_code
    }


def test_service_requires_an_explicit_enabled_model_configuration():
    repository = Mock()
    repository.get_draft.return_value = _draft()
    service = SmartEntryService(repository, Mock(), Mock())

    with pytest.raises(ApplicationError) as raised:
        service.analyze_draft(
            "user-1",
            "draft-1",
            expected_version=3,
            locale="zh-CN",
            weight_kg=None,
        )

    assert raised.value.code == "AI_NOT_CONFIGURED"
    assert raised.value.processing_mode == "agent"
    repository.mark_agent_failed.assert_called_once()
