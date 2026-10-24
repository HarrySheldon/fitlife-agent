"""Pure domain checks against an authorization snapshot supplied by trusted code.

This module neither derives consent from model output nor persists consent.
Repository calls still require the authenticated owner independently of this check.
"""
from dataclasses import dataclass


def require_domain(domain: str, authorized_domains: frozenset[str]) -> None:
    if not isinstance(authorized_domains, frozenset) or domain not in authorized_domains:
        raise PermissionError("DOMAIN_NOT_AUTHORIZED")


def require_change_domain(domain: str, change_domains: frozenset[str]) -> None:
    """Writing is a separate grant from reading.

    A task may read diet history to answer a question while being authorised to
    change training only. Treating the read grant as a write grant is how a
    read-only task ends up rewriting a plan.
    """
    if not isinstance(change_domains, frozenset) or domain not in change_domains:
        raise PermissionError("CHANGE_DOMAIN_NOT_AUTHORIZED")


@dataclass(frozen=True)
class AuthorizedPlanWrites:
    """Read grant and change grant for one task, both from trusted storage."""

    owner_id: str
    read_domains: frozenset[str]
    change_domains: frozenset[str]

    def __post_init__(self):
        if not isinstance(self.owner_id, str) or not self.owner_id.strip():
            raise ValueError("AUTHENTICATED_OWNER_REQUIRED")
        if not isinstance(self.read_domains, frozenset) or not isinstance(self.change_domains, frozenset):
            raise ValueError("TRUSTED_DOMAIN_SNAPSHOT_REQUIRED")
        if not self.change_domains <= self.read_domains:
            # Changing a domain you were never allowed to read is incoherent.
            raise ValueError("CHANGE_DOMAIN_NOT_READABLE")

    def require_read(self, domain: str) -> None:
        require_domain(domain, self.read_domains)

    def require_change(self, domain: str) -> None:
        require_change_domain(domain, self.change_domains)


@dataclass(frozen=True)
class AuthorizedTaskReads:
    """Bind reads to an authenticated owner and trusted stored consent snapshot.

    Construct this in application code after authentication and loading the user's
    decision. Model responses are not a source for either argument.
    """
    repository: object
    owner_id: str
    authorized_domains: frozenset[str]

    def __post_init__(self):
        if not isinstance(self.owner_id, str) or not self.owner_id.strip():
            raise ValueError("AUTHENTICATED_OWNER_REQUIRED")
        if not isinstance(self.authorized_domains, frozenset):
            raise ValueError("TRUSTED_DOMAIN_SNAPSHOT_REQUIRED")

    def read_meals(self):
        require_domain("diet", self.authorized_domains)
        return self.repository.read_meals(self.owner_id)

    def read_workouts(self):
        require_domain("training", self.authorized_domains)
        return self.repository.read_workouts(self.owner_id)
