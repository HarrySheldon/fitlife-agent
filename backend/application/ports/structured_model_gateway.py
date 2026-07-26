from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel


StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)


@dataclass(frozen=True)
class StructuredModelResult:
    output: BaseModel
    model: str
    usage: dict[str, int]


@runtime_checkable
class StructuredModelGateway(Protocol):
    model: str

    def parse_structured(
        self,
        *,
        instructions: str,
        input_text: str,
        response_model: type[StructuredOutput],
    ) -> StructuredModelResult: ...
