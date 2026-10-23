from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SkillSearchArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=8, ge=1, le=8, strict=True)


class ResourceReadArgs(ToolArgs):
    resource_id: str = Field(min_length=1, max_length=160)


class QueryArgs(ToolArgs):
    domain: Literal['profile', 'training', 'diet']
    fields: list[str] = Field(min_length=1, max_length=20)
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode='after')
    def bounded_dates(self):
        if self.domain != 'profile':
            if self.start_date is None or self.end_date is None:
                raise ValueError('DATE_RANGE_REQUIRED')
            if not 0 <= (self.end_date - self.start_date).days <= 89:
                raise ValueError('DATE_RANGE_TOO_LARGE')
        return self


class KnowledgeSearchArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=1000)
    scope: Literal['training', 'nutrition', 'general'] = 'general'
    top_k: int = Field(default=3, ge=1, le=5, strict=True)


class TrainingExercise(ToolArgs):
    name: str = Field(min_length=1, max_length=80, pattern=r'^[^<>\[\]\r\n]+$')
    sets: int = Field(ge=1, le=10, strict=True)
    reps: int = Field(ge=1, le=100, strict=True)
    rest_seconds: int = Field(ge=0, le=600, strict=True)


class CalculateArgs(ToolArgs):
    operation: Literal['validate_training', 'workout_analysis', 'meal_analysis']
    input_ref: str | None = Field(default=None, max_length=100)
    targets_ref: str | None = Field(default=None, max_length=100)
    exercises: list[TrainingExercise] = Field(default_factory=list, max_length=12)

    @model_validator(mode='after')
    def required_inputs(self):
        if self.operation == 'validate_training':
            if not self.exercises or self.input_ref is not None or self.targets_ref is not None:
                raise ValueError('SUGGESTION_INPUT_REQUIRED')
        elif not self.input_ref or self.exercises:
            raise ValueError('OBSERVATION_REQUIRED')
        if self.operation == 'meal_analysis' and not self.targets_ref:
            raise ValueError('TARGETS_REFERENCE_REQUIRED')
        return self
