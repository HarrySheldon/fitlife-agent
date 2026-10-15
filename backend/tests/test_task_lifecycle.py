from datetime import datetime, timedelta, timezone
from dataclasses import replace

import pytest

from backend.domain.errors import ApplicationError


def test_lifecycle_module_exports_owner_checked_drafts():
    from backend.agent.tasks.lifecycle import BusinessDraft, export_business_draft
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    draft = BusinessDraft(
        task_id="task-1", owner_id="owner", version=2,
        validated_input={"goal": "training"}, pending_questions=("Which days?",),
        candidate={"days": 3}, counters={"repair_rounds": 1},
        dependencies=("profile-v2",), run_links=("run-1",),
        expires_at=now + timedelta(hours=1),
    )
    exported = export_business_draft(draft, "owner", clock=lambda: now, expected_version=2)
    assert exported == {
        "classification": "business_draft", "task_id": "task-1", "version": 2,
        "validated_input": {"goal": "training"}, "pending_questions": ["Which days?"],
        "candidate": {"days": 3}, "counters": {"repair_rounds": 1},
        "dependencies": ["profile-v2"], "run_links": ["run-1"],
        "expires_at": draft.expires_at.isoformat(),
    }
    exported["candidate"]["days"] = 99
    assert draft.candidate["days"] == 3
    for resource, owner in ((None, "owner"), (draft, "foreign"), (replace(draft, deleted=True), "owner")):
        with pytest.raises(ApplicationError) as error:
            export_business_draft(resource, owner, clock=lambda: now)
        assert (error.value.status_code, error.value.code, error.value.message) == (404, "TASK_NOT_FOUND", "TASK_NOT_FOUND")
        assert "owner" not in str(error.value)
    with pytest.raises(ValueError, match="AUTHENTICATED_OWNER_REQUIRED"):
        export_business_draft(draft, "", clock=lambda: now)
    with pytest.raises(ApplicationError) as error:
        export_business_draft(draft, "owner", clock=lambda: now, expected_version=1)
    assert error.value.status_code == 409
    with pytest.raises(ApplicationError) as error:
        export_business_draft(draft, "owner", clock=lambda: draft.expires_at)
    assert error.value.status_code == 410


def test_lifecycle_requires_aware_clock_and_no_implicit_expiry():
    from backend.agent.tasks.lifecycle import BusinessDraft, export_business_draft
    draft = BusinessDraft("task-1", "owner", 1, {}, (), None, {}, (), ())
    assert draft.expires_at is None
    with pytest.raises(ValueError, match="aware"):
        export_business_draft(draft, "owner", clock=datetime.now)


def test_diagnostics_are_bounded_metadata_without_business_body():
    from backend.agent.tasks.lifecycle import DiagnosticRecord
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    record = DiagnosticRecord("transition", 1, 2, now, "task-1", "run-1")
    assert set(record.to_dict()) == {"classification", "category", "version", "count", "time", "task_id", "run_id"}
    assert record.to_dict()["classification"] == "diagnostic"
    with pytest.raises(TypeError):
        DiagnosticRecord("transition", 1, 2, now, "task-1", "run-1", body="private health")
    for changes in ({"category": "private health"}, {"task_id": "a" * 129}, {"run_id": "health text"}, {"count": -1}, {"version": True}, {"time": datetime.now()}):
        with pytest.raises(ValueError):
            replace(record, **changes)
