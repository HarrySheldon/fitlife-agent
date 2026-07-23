from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

import pandas as pd

from backend.schemas import MealRecord, UserProfile, WorkoutRecord


@runtime_checkable
class FitnessRepository(Protocol):
    def read_profile(self, user_id: str | None = None) -> UserProfile: ...

    def write_profile(self, profile: UserProfile, user_id: str | None = None) -> None: ...

    def update_profile_atomically(
        self,
        update: Callable[[UserProfile], UserProfile],
        user_id: str | None = None,
    ) -> UserProfile: ...

    def read_meals(self, user_id: str | None = None) -> pd.DataFrame: ...

    def read_workouts(self, user_id: str | None = None) -> pd.DataFrame: ...

    def append_meal(self, record: MealRecord, user_id: str | None = None) -> None: ...

    def append_workout(self, record: WorkoutRecord, user_id: str | None = None) -> None: ...
