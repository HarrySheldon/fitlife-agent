from typing import Protocol

from backend.domain.user_preferences import UserPreferences


class UserPreferencesRepository(Protocol):
    def get(self, user_id: str) -> UserPreferences | None: ...

    def save(self, user_id: str, preferences: UserPreferences) -> None: ...

