"""Restricted description parser. Nutrition and state are deterministic decisions."""
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, ValidationError

from backend.agent.structured_workflow import run_structured_agent
from backend.agent.tasks.input_contracts import EntryCandidateDTO, EntryInput


class EntrySuggestion(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    item_id: StrictStr = Field(min_length=1)
    name: StrictStr | None = Field(default=None, min_length=1)
    amount: StrictInt | StrictFloat | None = Field(default=None, gt=0)
    unit: StrictStr | None = Field(default=None, min_length=1)
    intake_ratio: StrictInt | StrictFloat | None = Field(default=None, gt=0, le=1)


class EntrySuggestions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    suggestions: list[EntrySuggestion] = Field(default_factory=list, max_length=100)


def parse_entry_descriptions(*, user_id, draft, candidates, binding, gateway_resolver):
    """Send only current unresolved food segments and their allowed parse fields."""
    allowed = {candidate.id for candidate in candidates}
    payload = EntryInput(current_meal_text='\n'.join(candidate.raw_text for candidate in candidates),
        missing_fields=list(dict.fromkeys(field for item in draft.payload.interaction.items
            if item.item_id in allowed for field in item.missing_fields)),
        catalog_matches=[{'food_id': choice.id, 'name': choice.name, 'source': choice.source}
            for candidate in candidates for choice in candidate.catalog_choices],
        candidates=[EntryCandidateDTO(id=candidate.id, kind='food', source_segment=candidate.raw_text,
            issues=list(candidate.issues), explicit_values={key: value for key, value in candidate.values.items()
                if key in ('name', 'amount', 'unit', 'intake_ratio')}) for candidate in candidates])
    from backend.agent.tasks.contracts import TaskRef
    try:
        result = run_structured_agent(operation='smart_entry', question=payload.current_meal_text,
            user_id=user_id, input_text=payload.model_dump_json(), response_model=EntrySuggestions,
            instructions=('Parse only the supplied food descriptions. Return existing item IDs and explicit '
                          'food name, amount, unit or intake ratio only. Do not invent portions. '
                          'Do not provide nutrition, identity, training, or saved state.'),
            gateway_resolver=gateway_resolver, task_ref=TaskRef(draft.id, draft.version),
            task_budget_binding=binding)
    except ValidationError as error:
        from backend.domain.errors import ApplicationError
        raise ApplicationError(code='ENTRY_MODEL_OUTPUT_INVALID', message='ENTRY_MODEL_OUTPUT_INVALID',
            status_code=422, processing_mode='agent', run_id=getattr(error, 'run_id', None)) from None
    output = EntrySuggestions.model_validate(result.output)
    seen = set()
    for suggestion in output.suggestions:
        if suggestion.item_id not in allowed or suggestion.item_id in seen:
            from backend.domain.errors import ApplicationError
            raise ApplicationError(code='ENTRY_MODEL_TARGET_INVALID', message='ENTRY_MODEL_TARGET_INVALID',
                status_code=422, processing_mode='agent', run_id=result.run_id)
        seen.add(suggestion.item_id)
    return result, output
