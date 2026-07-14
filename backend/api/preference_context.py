from backend.config import get_settings
from backend.domain.user_preferences import UserPreferences
from backend.infrastructure.settings.file_user_preferences_repository import FileUserPreferencesRepository
from backend.schemas import AuthenticatedUser


def preferences_for(user: AuthenticatedUser | None) -> UserPreferences:
    if user is None:
        return UserPreferences()
    repository = FileUserPreferencesRepository(get_settings().data_dir)
    return repository.get(user.user_id) or UserPreferences()

