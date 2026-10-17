from datetime import datetime, timezone

import pytest

from backend.application.use_cases.expire_agent_tasks import ExpireAgentTasks


def test_expiry_defaults_to_dry_run_and_passes_explicit_owner_and_cutoff():
    class Repository:
        def expire_tasks(self, user_id, *, cutoff, dry_run):
            assert user_id == 'owner'
            assert cutoff == datetime(2026, 1, 1, tzinfo=timezone.utc)
            assert dry_run is True
            return ('draft-1',)

    result = ExpireAgentTasks(Repository(), clock=lambda: datetime(2026, 1, 2, tzinfo=timezone.utc)).execute(
        'owner', cutoff=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    assert result.task_ids == ('draft-1',)
    assert result.count == 1


@pytest.mark.parametrize('cutoff', [datetime(2026, 1, 1), datetime(2026, 1, 3, tzinfo=timezone.utc), 'invalid'])
def test_expiry_rejects_invalid_naive_or_future_cutoff_before_repository(cutoff):
    class Repository:
        def expire_tasks(self, *args, **kwargs):
            pytest.fail('Invalid cutoff must not reach repository')

    with pytest.raises(ValueError):
        ExpireAgentTasks(Repository(), clock=lambda: datetime(2026, 1, 2, tzinfo=timezone.utc)).execute(
            'owner', cutoff=cutoff, dry_run=False)
