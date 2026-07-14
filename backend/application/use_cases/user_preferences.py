from __future__ import annotations

from backend.application.ports.user_preferences_repository import UserPreferencesRepository
from backend.domain.user_preferences import AppLanguage, UnitSystem, UserPreferences, validate_iana_timezone


class GetUserPreferences:
    def __init__(self, repository: UserPreferencesRepository) -> None:
        self.repository = repository

    def execute(
        self,
        user_id: str,
        *,
        language_hint: str | None = None,
        timezone_hint: str | None = None,
    ) -> UserPreferences:
        stored = self.repository.get(user_id)
        if stored is not None:
            return stored

        preferences = UserPreferences(
            language=_language_from_hint(language_hint),
            timezone=_timezone_from_hint(timezone_hint),
        )
        self.repository.save(user_id, preferences)
        return preferences


class UpdateUserPreferences:
    def __init__(self, repository: UserPreferencesRepository) -> None:
        self.repository = repository

    def execute(
        self,
        user_id: str,
        *,
        language: AppLanguage | None = None,
        unit_system: UnitSystem | None = None,
        timezone: str | None = None,
    ) -> UserPreferences:
        current = self.repository.get(user_id) or UserPreferences()
        updates = {}
        if language is not None:
            updates["language"] = language
        if unit_system is not None:
            updates["unit_system"] = unit_system
        if timezone is not None:
            updates["timezone"] = validate_iana_timezone(timezone)
        saved = current.model_copy(update=updates)
        self.repository.save(user_id, saved)
        return saved


def _language_from_hint(value: str | None) -> AppLanguage:
    primary = (value or "").split(",", 1)[0].strip().lower()
    return "zh-CN" if primary.startswith("zh") else "en-US"


def _timezone_from_hint(value: str | None) -> str:
    if not value:
        return "UTC"
    try:
        return validate_iana_timezone(value)
    except ValueError:
        return "UTC"

