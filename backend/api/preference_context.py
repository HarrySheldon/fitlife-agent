from backend.config import get_settings
from backend.domain.user_preferences import UserPreferences
from backend.infrastructure.settings.postgres_user_preferences_repository import PostgresUserPreferencesRepository
from backend.infrastructure.postgres.runtime import get_database
from backend.schemas import AuthenticatedUser


def preferences_for(user: AuthenticatedUser | None) -> UserPreferences:
    if user is None:
        return UserPreferences()
    repository = PostgresUserPreferencesRepository(get_database(), get_settings().data_dir)
    return repository.get(user.user_id) or UserPreferences()

