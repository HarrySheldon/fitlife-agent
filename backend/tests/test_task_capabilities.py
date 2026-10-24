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


def test_read_grant_does_not_imply_change_grant():
    from backend.agent.tasks.capabilities import AuthorizedPlanWrites

    writes = AuthorizedPlanWrites("authenticated", frozenset({"training", "diet"}),
                                  frozenset({"training"}))

    # Reading diet history is allowed; changing it is not.
    writes.require_read("diet")
    writes.require_change("training")
    with pytest.raises(PermissionError, match="CHANGE_DOMAIN_NOT_AUTHORIZED"):
        writes.require_change("diet")


def test_change_grant_must_be_readable_and_typed():
    from backend.agent.tasks.capabilities import AuthorizedPlanWrites

    with pytest.raises(ValueError, match="CHANGE_DOMAIN_NOT_READABLE"):
        AuthorizedPlanWrites("authenticated", frozenset({"training"}), frozenset({"diet"}))
    with pytest.raises(ValueError, match="TRUSTED_DOMAIN_SNAPSHOT_REQUIRED"):
        AuthorizedPlanWrites("authenticated", frozenset({"training"}), {"training"})
    with pytest.raises(ValueError, match="AUTHENTICATED_OWNER_REQUIRED"):
        AuthorizedPlanWrites("", frozenset({"training"}), frozenset({"training"}))
