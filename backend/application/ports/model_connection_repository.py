from typing import Protocol

from backend.domain.model_connection import ModelConnection, PublicModelConnection


class ModelConnectionRepository(Protocol):
    def get(self, user_id: str) -> ModelConnection | None: ...

    def get_public(self, user_id: str) -> PublicModelConnection | None: ...

    def save(self, user_id: str, connection: ModelConnection) -> None: ...
