from typing import Protocol

from backend.domain.model_connection import ModelConnection


class ModelConnectionRepository(Protocol):
    def get(self, user_id: str) -> ModelConnection | None: ...

    def save(self, user_id: str, connection: ModelConnection) -> None: ...
