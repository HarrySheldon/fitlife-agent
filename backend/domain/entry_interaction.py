from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from decimal import Decimal, DecimalException
from datetime import datetime
import math
from typing import Literal

from backend.domain.smart_entry import ResolvedCandidate, SmartEntryDomainError
from backend.domain.meals import FoodDefinition, FoodPortion, portion_from_food


ItemState = Literal['needs_clarification', 'ready', 'saved', 'discarded']
FieldSource = Literal['unknown', 'estimated', 'catalog', 'user_provided', 'measured']


@dataclass(frozen=True)
class EntryQuestion:
    item_id: str
    field: str
    portion_options: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        fields = {'name', 'selected_catalog_id', 'amount', 'unit', 'intake_ratio',
                  'calories', 'carbs', 'protein', 'fat', 'basis_type'}
        if (not isinstance(self.item_id, str) or not self.item_id.strip()
                or not isinstance(self.field, str) or self.field not in fields
                or any(not isinstance(v, str) or not v.strip() for v in self.portion_options)):
            raise SmartEntryDomainError('QUESTION_INVALID')


@dataclass(frozen=True)
class EntryQuestionGroup:
    group_id: str
    asked_at: str
    expected_version: int
    questions: tuple[EntryQuestion, ...]
    answered: bool = False

    def __post_init__(self) -> None:
        if (not isinstance(self.group_id, str) or not self.group_id.strip()
                or not self.asked_at or type(self.expected_version) is not int
                or self.expected_version < 1 or type(self.answered) is not bool or not self.questions):
            raise SmartEntryDomainError('QUESTION_GROUP_INVALID')
        try:
            timestamp = datetime.fromisoformat(self.asked_at.replace('Z', '+00:00'))
            if timestamp.tzinfo is None:
                raise ValueError
        except (AttributeError, TypeError, ValueError):
            raise SmartEntryDomainError('QUESTION_GROUP_TIMESTAMP_INVALID') from None
        targets = [(question.item_id, question.field) for question in self.questions]
        if len(set(targets)) != len(targets):
            raise SmartEntryDomainError('QUESTION_TARGET_DUPLICATE')


@dataclass(frozen=True)
class CatalogDependency:
    item_id: str
    catalog_id: str
    signature: str

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip()
               for value in (self.item_id, self.catalog_id, self.signature)):
            raise SmartEntryDomainError('CATALOG_DEPENDENCY_INVALID')


@dataclass(frozen=True)
class EntryItem:
    item_id: str
    revision: int
    state: ItemState
    values: dict[str, object]
    sources: dict[str, FieldSource]
    missing_fields: tuple[str, ...]
    assumptions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.item_id, str) or not self.item_id.strip():
            raise SmartEntryDomainError('ITEM_ID_INVALID')
        if type(self.revision) is not int or self.revision < 1:
            raise SmartEntryDomainError('ITEM_REVISION_INVALID')
        if self.state not in ('needs_clarification', 'ready', 'saved', 'discarded'):
            raise SmartEntryDomainError('ITEM_STATE_INVALID')
        if self.values.keys() != self.sources.keys():
            raise SmartEntryDomainError('FIELD_SOURCE_REQUIRED')
        if any(source not in ('unknown', 'estimated', 'catalog', 'user_provided', 'measured')
               for source in self.sources.values()):
            raise SmartEntryDomainError('FIELD_SOURCE_INVALID')
        object.__setattr__(self, 'values', deepcopy(self.values))
        object.__setattr__(self, 'sources', dict(self.sources))


@dataclass(frozen=True)
class EntryInteraction:
    schema_version: Literal[1, 2] = 1
    clarification_rounds: int = 0
    items: tuple[EntryItem, ...] = ()
    active: bool = False
    status: Literal['collecting', 'awaiting_clarification', 'awaiting_confirmation', 'partially_saved', 'completed', 'cancelled', 'expired'] = 'collecting'
    question_groups: tuple[EntryQuestionGroup, ...] = ()
    dependencies: tuple[CatalogDependency, ...] = ()
    run_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.active) is not bool:
            raise SmartEntryDomainError('INTERACTION_ACTIVE_INVALID')
        if type(self.schema_version) is not int or self.schema_version not in (1, 2):
            raise SmartEntryDomainError('INTERACTION_SCHEMA_INVALID')
        if type(self.clarification_rounds) is not int or self.clarification_rounds < 0:
            raise SmartEntryDomainError('CLARIFICATION_ROUNDS_INVALID')
        if len({item.item_id for item in self.items}) != len(self.items):
            raise SmartEntryDomainError('ITEM_ID_DUPLICATE')
        if self.status not in ('collecting', 'awaiting_clarification', 'awaiting_confirmation', 'partially_saved', 'completed', 'cancelled', 'expired'):
            raise SmartEntryDomainError('INTERACTION_STATUS_INVALID')
        if self.clarification_rounds > 2 or len(self.question_groups) > 2:
            raise SmartEntryDomainError('CLARIFICATION_LIMIT_EXCEEDED')
        if len(self.question_groups) != self.clarification_rounds:
            raise SmartEntryDomainError('QUESTION_ROUNDS_INVALID')
        if len({group.group_id for group in self.question_groups}) != len(self.question_groups):
            raise SmartEntryDomainError('QUESTION_GROUP_DUPLICATE')
        if sum(not group.answered for group in self.question_groups) > 1:
            raise SmartEntryDomainError('QUESTION_GROUP_PENDING_DUPLICATE')
        item_ids = {item.item_id for item in self.items}
        if any(question.item_id not in item_ids for group in self.question_groups for question in group.questions):
            raise SmartEntryDomainError('QUESTION_ITEM_INVALID')
        if (len({dep.item_id for dep in self.dependencies}) != len(self.dependencies)
                or any(dep.item_id not in item_ids for dep in self.dependencies)):
            raise SmartEntryDomainError('CATALOG_DEPENDENCY_INVALID')
        if any(not isinstance(run_id, str) or not run_id.strip() for run_id in self.run_ids):
            raise SmartEntryDomainError('INTERACTION_RUN_ID_INVALID')


def replace_fields(
    item: EntryItem,
    updates: dict[str, object],
    sources: dict[str, FieldSource],
) -> EntryItem:
    if item.state in ('saved', 'discarded'):
        raise SmartEntryDomainError('ITEM_NOT_EDITABLE')
    if updates.keys() != sources.keys():
        raise SmartEntryDomainError('FIELD_SOURCE_REQUIRED')
    if any(source not in ('unknown', 'estimated', 'catalog', 'user_provided', 'measured')
           for source in sources.values()):
        raise SmartEntryDomainError('FIELD_SOURCE_INVALID')
    return replace(
        item, revision=item.revision + 1, state='needs_clarification',
        values=deepcopy({**item.values, **updates}),
        sources={**item.sources, **sources},
    )


def project_interaction(
    candidates: tuple[ResolvedCandidate, ...],
    *, schema_version: Literal[1, 2] = 1,
) -> EntryInteraction:
    """Read old drafts conservatively, retaining the parser's persistent IDs."""
    items = []
    for candidate in candidates:
        if candidate.kind != 'food':
            continue
        values = deepcopy(candidate.values)
        estimated = (values.get('is_estimate') is True
                     or values.get('source') == 'agent_estimate'
                     or candidate.provenance.get('source') == 'agent_estimate')
        source: FieldSource = 'estimated' if estimated else 'unknown'
        sources = {key: source for key in values}
        missing = tuple(key for key in ('amount', 'unit', 'calories', 'carbs', 'protein', 'fat')
                        if values.get(key) is None)
        items.append(EntryItem(
            candidate.id, 1,
            'needs_clarification',
            values, sources, missing, candidate.assumptions,
        ))
    return EntryInteraction(schema_version=schema_version, items=tuple(items))


def food_entry_item(candidate: ResolvedCandidate) -> EntryItem:
    """Start new interaction food items without accepting generated nutrition."""
    if candidate.kind != 'food':
        raise SmartEntryDomainError('ITEM_KIND_INVALID')
    item = project_interaction((candidate,), schema_version=2).items[0]
    if candidate.selected_catalog_id is not None:
        return item
    values = dict(item.values)
    sources = dict(item.sources)
    for field in ('calories', 'carbs', 'protein', 'fat'):
        values[field] = None
        sources[field] = 'unknown'
    missing = tuple(dict.fromkeys((*item.missing_fields, 'calories', 'carbs', 'protein', 'fat')))
    return replace(item, values=values, sources=sources, missing_fields=missing)


def catalog_portion(
    food: FoodDefinition, *, amount: float, unit: str, intake_ratio: float = 1,
) -> FoodPortion:
    if (isinstance(intake_ratio, bool) or not isinstance(intake_ratio, (int, float))
            or not math.isfinite(intake_ratio) or not 0 < intake_ratio <= 1):
        raise SmartEntryDomainError('INTAKE_RATIO_INVALID')
    # Validate the original portion before scaling so invalid observations never
    # become valid as a side effect of multiplication.
    portion_from_food(food, amount=amount, unit=unit)
    try:
        effective_amount = float(Decimal(str(amount)) * Decimal(str(intake_ratio)))
    except (DecimalException, OverflowError):
        raise SmartEntryDomainError('FOOD_PORTION_SCALE_INVALID') from None
    return portion_from_food(food, amount=effective_amount, unit=unit)
