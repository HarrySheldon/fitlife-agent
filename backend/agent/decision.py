"""Provider-neutral decisions; validation never grants execution authority."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    @field_validator('*', mode='after')
    @classmethod
    def no_blank_text(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError('Blank decision text')
        return value


class ToolCall(StrictDecision):
    kind: Literal['call'] = 'call'
    call_id: str = Field(min_length=1, max_length=64)
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict[str, object]


class AskDecision(StrictDecision):
    kind: Literal['ask'] = 'ask'
    question: str = Field(min_length=1, max_length=1200)


class FinalDecision(StrictDecision):
    kind: Literal['final'] = 'final'
    body: str = Field(min_length=1, max_length=12000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=64)


AgentDecision = Annotated[ToolCall | AskDecision | FinalDecision, Field(discriminator='kind')]


class DecisionEnvelope(StrictDecision):
    decision: AgentDecision
