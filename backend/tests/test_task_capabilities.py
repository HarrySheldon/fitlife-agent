import pytest

from backend.agent.tasks.capabilities import require_domain


def test_domain_permission_is_fail_closed():
    require_domain("diet", frozenset({"diet"}))
    with pytest.raises(PermissionError, match="DOMAIN_NOT_AUTHORIZED"):
        require_domain("training", frozenset({"diet"}))


def test_repository_reads_always_use_bound_authenticated_owner():
    from backend.agent.tasks.capabilities import AuthorizedTaskReads
    class Repository:
        def read_meals(self, owner):
            return owner
        def read_workouts(self, owner):
            return owner
    reads = AuthorizedTaskReads(Repository(), "authenticated", frozenset({"diet"}))
    assert reads.read_meals() == "authenticated"
    with pytest.raises(TypeError):
        reads.read_meals("forged")
    with pytest.raises(PermissionError):
        reads.read_workouts()
