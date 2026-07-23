from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from backend.schemas import MealRecord, UserProfile, WorkoutRecord
from backend.tools import data_access


class FileFitnessRepository:
    """File-backed adapter preserving the existing per-user JSON/CSV format."""

    def read_profile(self, user_id: str | None = None) -> UserProfile:
        return data_access.read_profile(user_id)

    def write_profile(self, profile: UserProfile, user_id: str | None = None) -> None:
        data_access.write_profile(profile, user_id)

    def update_profile_atomically(
        self,
        update: Callable[[UserProfile], UserProfile],
        user_id: str | None = None,
    ) -> UserProfile:
        return data_access.update_profile_atomically(update, user_id)

    def read_meals(self, user_id: str | None = None) -> pd.DataFrame:
        return data_access.read_meals(user_id)

    def read_workouts(self, user_id: str | None = None) -> pd.DataFrame:
        return data_access.read_workouts(user_id)

    def append_meal(self, record: MealRecord, user_id: str | None = None) -> None:
        data_access.append_meal(record, user_id)

    def append_workout(self, record: WorkoutRecord, user_id: str | None = None) -> None:
        data_access.append_workout(record, user_id)
