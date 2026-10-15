"""Pure domain checks against an authorization snapshot supplied by trusted code.

This module neither derives consent from model output nor persists consent.
Repository calls still require the authenticated owner independently of this check.
"""
from dataclasses import dataclass


def require_domain(domain: str, authorized_domains: frozenset[str]) -> None:
    if not isinstance(authorized_domains, frozenset) or domain not in authorized_domains:
        raise PermissionError("DOMAIN_NOT_AUTHORIZED")


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
