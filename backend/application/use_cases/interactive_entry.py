"""Owner-scoped interactive meal commands; models only propose bounded patches."""
from dataclasses import replace
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator

from backend.agent.safety import check_input
from backend.agent.tasks.contracts import task_error
from backend.application.ports.smart_entry_repository import SmartEntryRepositoryError
from backend.application.ports.task_budget_repository import TaskBudgetBinding, TaskBudgetConflict
from backend.domain.entry_interaction import (
    CatalogDependency, EntryQuestion, EntryQuestionGroup, food_entry_item,
)
from backend.domain.entry_resolution import catalog_signature, resolve_item, validate_updates
from backend.domain.errors import ApplicationError
from backend.domain.meals import MealDomainError
from backend.domain.smart_entry import SmartEntryDomainError
from backend.safety.business_scope import decide_business_scope


class EntryCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: StrictInt = Field(ge=1)
    key: str = Field(min_length=1, max_length=200)


class EntryAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    item_id: str = Field(min_length=1)
    field: str
    value: object = None

    @model_validator(mode='after')
    def writable_answer(self):
        validate_updates({self.field: self.value})
        return self


class AnswerCommand(EntryCommand):
    question_group_id: str = Field(min_length=1)
    answers: list[EntryAnswer]


class CorrectionCommand(EntryCommand):
    item_id: str = Field(min_length=1)
    item_revision: StrictInt = Field(ge=1)
    updates: dict[str, object]

    @model_validator(mode='after')
    def writable_updates(self):
        validate_updates(self.updates)
        return self


class ItemSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    item_id: str = Field(min_length=1)
    item_revision: StrictInt = Field(ge=1)


class ConfirmItemsCommand(EntryCommand):
    selections: list[ItemSelection] = Field(min_length=1)
    accepted_estimates: list[ItemSelection] = Field(default_factory=list)

    @model_validator(mode='after')
    def accepted_subset(self):
        selected = {(item.item_id, item.item_revision) for item in self.selections}
        if any((item.item_id, item.item_revision) not in selected for item in self.accepted_estimates):
            raise ValueError('acceptance must select the same item revision')
        return self


def _error(code, status=422):
    return ApplicationError(code=code, message=code, status_code=status, processing_mode='agent')


def _command(model, **values):
    try:
        return model(**values)
    except ValidationError:
        raise _error('ENTRY_COMMAND_INVALID') from None


def _repository_error(error):
    mapped = {'DRAFT_NOT_FOUND': 'TASK_NOT_FOUND', 'DRAFT_EXPIRED': 'TASK_EXPIRED',
              'DRAFT_VERSION_CONFLICT': 'TASK_VERSION_CONFLICT',
              'IDEMPOTENCY_KEY_REUSED': 'IDEMPOTENCY_CONFLICT'}
    conflicts = {'ITEM_REVISION_CONFLICT', 'ITEM_NOT_READY', 'CATALOG_DEPENDENCY_CHANGED',
                 'INTERACTION_NOT_ACTIVE', 'ESTIMATE_ACCEPTANCE_REQUIRED'}
    return task_error(mapped[error.code]) if error.code in mapped else _error(error.code,
        409 if error.code in conflicts else 404 if error.code == 'ITEM_NOT_FOUND' else
        500 if error.code in {'SMART_ENTRY_CONFIRM_FAILED', 'SMART_ENTRY_DRAFT_CORRUPT',
                             'IDEMPOTENCY_RESPONSE_CORRUPT'} else 422)


class InteractiveEntryService:
    def __init__(self, repository, food_catalog, task_budgets, *, enabled=False,
                 gateway_resolver=None, clock=None, call_limit=16, token_limit=512000,
                 mutation_scope=None, model_available=None):
        self.repository = repository
        self.food_catalog = food_catalog
        self.task_budgets = task_budgets
        self.enabled = enabled
        self.gateway_resolver = gateway_resolver
        self.model_available = model_available
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.call_limit, self.token_limit = call_limit, token_limit
        self._mutation_scope = mutation_scope or (lambda _user: nullcontext())

    def _read(self, user, draft):
        try:
            return self.repository.read_interaction_draft(user, draft)
        except SmartEntryRepositoryError as error:
            raise _repository_error(error) from None

    def _prepare(self, user, draft_id, operation, command):
        if not self.enabled:
            raise _error('INTERACTIVE_ENTRY_DISABLED', 409)
        draft = self._read(user, draft_id)
        try:
            if isinstance(command, CorrectionCommand):
                validate_updates(command.updates)
            elif isinstance(command, AnswerCommand):
                for answer in command.answers:
                    validate_updates({answer.field: answer.value})
        except SmartEntryDomainError as error:
            raise _error(error.code) from None
        fingerprint = hashlib.sha256(json.dumps(
            {'operation': operation, **command.model_dump()}, sort_keys=True,
            ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        try:
            replay = self.repository.get_interaction_command_result(user, draft_id,
                idempotency_key=command.key, request_fingerprint=fingerprint)
        except SmartEntryRepositoryError as error:
            raise _repository_error(error) from None
        if replay is not None:
            return draft, fingerprint, replay
        if draft.version != command.expected_version:
            raise task_error('TASK_VERSION_CONFLICT')
        if draft.payload.interaction.status in ('completed', 'cancelled', 'expired'):
            raise _error('INTERACTION_NOT_EDITABLE', 409)
        check_input(draft.payload.raw_text)
        if decide_business_scope(draft.payload.raw_text).scope == 'out_of_scope':
            raise _error('BUSINESS_SCOPE_NOT_SUPPORTED')
        try:
            with self._mutation_scope(user):
                self._read(user, draft_id)
                self.task_budgets.initialize(user, draft_id, self.call_limit, self.token_limit)
        except TaskBudgetConflict:
            raise task_error('IDEMPOTENCY_CONFLICT') from None
        return draft, fingerprint, None

    def _execute(self, user, draft, command, fingerprint, payload):
        try:
            with self._mutation_scope(user):
                return self.repository.execute_interaction_command(user, draft.id,
                    expected_version=command.expected_version, idempotency_key=command.key,
                    request_fingerprint=fingerprint, transform=lambda current: payload)
        except SmartEntryRepositoryError as error:
            raise _repository_error(error) from None

    def _food(self, user, catalog_id):
        return self.food_catalog.get_visible_food(user, catalog_id) if catalog_id else None

    def _resolve(self, user, candidate, item, *, updates=None, increment=False):
        try:
            return self._resolve_food(user, candidate, item, updates=updates, increment=increment)
        except (SmartEntryDomainError, MealDomainError) as error:
            raise _error(error.code) from None

    def _resolve_food(self, user, candidate, item, *, updates=None, increment=False):
        updates = dict(updates or {})
        validate_updates(updates)
        explicit_catalog = 'selected_catalog_id' in updates
        catalog_id = updates.pop('selected_catalog_id', candidate.selected_catalog_id)
        if explicit_catalog and catalog_id is None and candidate.selected_catalog_id is not None:
            item = replace(item, values={**item.values, **{field: None for field in
                ('calories', 'carbs', 'protein', 'fat')}}, sources={**item.sources,
                **{field: 'unknown' for field in ('calories', 'carbs', 'protein', 'fat')}})
        if ('name' in updates and updates['name'] != item.values.get('name')
                and not explicit_catalog):
            catalog_id = None
            if isinstance(updates['name'], str):
                candidate = replace(candidate, subject_text=updates['name'])
            item = replace(item, values={**item.values, **{field: None for field in
                ('calories', 'carbs', 'protein', 'fat')}}, sources={**item.sources,
                **{field: 'unknown' for field in ('calories', 'carbs', 'protein', 'fat')}})
        food = self._food(user, catalog_id)
        if catalog_id and food is None:
            raise _error('SMART_ENTRY_CATALOG_NOT_VISIBLE')
        if (food is None and catalog_id is None and not explicit_catalog
                and (not updates or isinstance(updates.get('name'), str))):
            matches = self.food_catalog.search(user, candidate.subject_text, limit=10)
            query = candidate.subject_text.strip().casefold()
            exact = [food for food in matches if query in
                     {food.name.strip().casefold(), *(alias.strip().casefold() for alias in food.aliases)}]
            if len(exact) == 1:
                food, catalog_id = exact[0], exact[0].id
        item = resolve_item(item, food, updates=updates, increment=increment)
        if food is None and candidate.catalog_choices and item.missing_fields:
            item = replace(item, missing_fields=tuple(dict.fromkeys(
                ('selected_catalog_id', *item.missing_fields))))
        # Attribution follows the current catalog selection, never a previous
        # candidate or arbitrary catalog metadata. Field-level sources remain
        # on the interaction item and are copied when the item is confirmed.
        provenance = ({field: getattr(food, field) for field in
            ('source', 'source_name', 'source_record_id', 'dataset_version',
             'license', 'attribution', 'content_hash')} | {'catalog_id': food.id}
            if food is not None else {})
        candidate = replace(candidate, selected_catalog_id=catalog_id,
                            values=item.values, assumptions=item.assumptions,
                            provenance=provenance)
        dependency = CatalogDependency(item.item_id, catalog_id, catalog_signature(food)) if food else None
        return candidate, item, dependency

    def _questions(self, interaction, version, foods):
        pending = any(not group.answered for group in interaction.question_groups)
        missing = [item for item in interaction.items if item.state == 'needs_clarification']
        if missing and not pending and interaction.clarification_rounds < 2:
            questions = tuple(EntryQuestion(item.item_id, field,
                ((f'{foods[item.item_id].basis_amount:g}' if field == 'amount'
                  else foods[item.item_id].unit),)
                if item.item_id in foods and field in ('amount', 'unit') else ())
                for item in missing for field in item.missing_fields)
            if questions:
                group = EntryQuestionGroup(uuid4().hex, self.clock().isoformat(), version + 1, questions)
                interaction = replace(interaction,
                    question_groups=(*interaction.question_groups, group),
                    clarification_rounds=interaction.clarification_rounds + 1)
        status = ('partially_saved' if any(item.state == 'saved' for item in interaction.items)
                  else 'awaiting_clarification' if missing else 'awaiting_confirmation')
        return replace(interaction, status=status)

    def _payload(self, draft, candidates, items, dependencies, *, interaction=None):
        interaction = interaction or draft.payload.interaction
        foods = {dep.item_id: self._food(draft.user_id, dep.catalog_id) for dep in dependencies}
        foods = {key: food for key, food in foods.items() if food is not None}
        interaction = replace(interaction, schema_version=2, active=True,
                              items=tuple(items), dependencies=tuple(dependencies))
        interaction = self._questions(interaction, draft.version, foods)
        return replace(draft.payload, candidates=tuple(candidates), interaction=interaction)

    def start(self, user, draft_id, *, expected_version, key):
        command = _command(EntryCommand, expected_version=expected_version, key=key)
        draft, fingerprint, replay = self._prepare(user, draft_id, 'start', command)
        if replay is not None:
            return replay
        if draft.payload.interaction.active:
            for dependency in draft.payload.interaction.dependencies:
                item = next(item for item in draft.payload.interaction.items if item.item_id == dependency.item_id)
                if item.state in ('saved', 'discarded'):
                    continue
                food = self._food(user, dependency.catalog_id)
                if food is None or catalog_signature(food) != dependency.signature:
                    raise _error('CATALOG_DEPENDENCY_CHANGED', 409)
            payload = self._payload(draft, draft.payload.candidates, draft.payload.interaction.items,
                                    draft.payload.interaction.dependencies)
        else:
            candidates, items, dependencies = [], [], []
            for candidate in draft.payload.candidates:
                if candidate.kind == 'food':
                    candidate, item, dependency = self._resolve(user, candidate, food_entry_item(candidate))
                    items.append(item)
                    if dependency:
                        dependencies.append(dependency)
                candidates.append(candidate)
            payload = self._payload(draft, candidates, items, dependencies)
            unresolved = tuple(candidate for candidate in payload.candidates
                if candidate.kind == 'food' and candidate.selected_catalog_id is None)
            if (unresolved and self.gateway_resolver is not None
                    and (self.model_available is None or self.model_available(user))):
                from backend.agent.entry_workflow import parse_entry_descriptions
                result, suggestions = parse_entry_descriptions(user_id=user, draft=draft,
                    candidates=unresolved, binding=TaskBudgetBinding(self.task_budgets, user, draft_id),
                    gateway_resolver=lambda: self.gateway_resolver(user))
                by_id = {suggestion.item_id: suggestion for suggestion in suggestions.suggestions}
                revised, revised_items, revised_deps = [], [], list(payload.interaction.dependencies)
                item_map = {item.item_id: item for item in payload.interaction.items}
                for candidate in payload.candidates:
                    if candidate.id in by_id:
                        suggestion = by_id[candidate.id]
                        updates = suggestion.model_dump(exclude_none=True, exclude={'item_id'})
                        if suggestion.name:
                            candidate = replace(candidate, subject_text=suggestion.name)
                        # Resolve a suggested name only against the visible catalog.
                        if suggestion.name:
                            matches = self.food_catalog.search(user, suggestion.name, limit=10)
                            exact = [food for food in matches if suggestion.name.casefold() in
                                {food.name.casefold(), *(alias.casefold() for alias in food.aliases)}]
                            if len(exact) == 1:
                                updates['selected_catalog_id'] = exact[0].id
                        candidate, item, dependency = self._resolve(user, candidate, item_map[candidate.id], updates=updates)
                        # Model observations remain estimates, including explicit-looking portions.
                        item = replace(item, sources={key: ('estimated' if key in updates else source)
                            for key, source in item.sources.items()},
                            values={**item.values, 'is_estimate': True},
                            assumptions=(*item.assumptions, 'Description interpreted by model.'))
                        item = replace(item, sources={**item.sources, 'is_estimate': 'estimated'})
                        candidate = replace(candidate, values=item.values, assumptions=item.assumptions)
                        item_map[candidate.id] = item
                        if dependency:
                            revised_deps.append(dependency)
                    revised.append(candidate)
                fresh = replace(payload.interaction, question_groups=(), clarification_rounds=0,
                                run_ids=(*payload.interaction.run_ids, result.run_id))
                payload = self._payload(draft, revised, item_map.values(), revised_deps, interaction=fresh)
        return self._execute(user, draft, command, fingerprint, payload)

    def answer(self, user, draft_id, *, expected_version, key, question_group_id, answers):
        command = _command(AnswerCommand, expected_version=expected_version, key=key,
                                question_group_id=question_group_id, answers=answers)
        draft, fingerprint, replay = self._prepare(user, draft_id, 'answer', command)
        if replay is not None:
            return replay
        interaction = draft.payload.interaction
        if not interaction.active or not interaction.question_groups:
            raise _error('QUESTION_GROUP_NOT_FOUND')
        group = interaction.question_groups[-1]
        if group.group_id != question_group_id:
            raise _error('QUESTION_GROUP_NOT_CURRENT', 409)
        if group.answered:
            raise _error('QUESTION_GROUP_ALREADY_ANSWERED', 409)
        allowed = {(question.item_id, question.field) for question in group.questions}
        updates = {}
        seen = set()
        for answer in command.answers:
            target = (answer.item_id, answer.field)
            if target not in allowed or target in seen:
                raise _error('QUESTION_TARGET_INVALID')
            seen.add(target)
            updates.setdefault(answer.item_id, {})
            if answer.value is not None:
                updates.setdefault(answer.item_id, {})[answer.field] = answer.value
        groups = (*interaction.question_groups[:-1], replace(group, answered=True))
        return self._edit(user, draft, command, fingerprint, updates,
                          replace(interaction, question_groups=groups))

    def correct(self, user, draft_id, *, expected_version, key, item_id, item_revision, updates):
        command = _command(CorrectionCommand, expected_version=expected_version, key=key, item_id=item_id,
                                    item_revision=item_revision, updates=updates)
        draft, fingerprint, replay = self._prepare(user, draft_id, 'correct', command)
        if replay is not None:
            return replay
        item = next((item for item in draft.payload.interaction.items if item.item_id == item_id), None)
        if item is None:
            raise _error('ITEM_NOT_FOUND', 404)
        if item.revision != item_revision:
            raise task_error('TASK_VERSION_CONFLICT')
        if not draft.payload.interaction.active:
            raise _error('INTERACTION_NOT_ACTIVE', 409)
        return self._edit(user, draft, command, fingerprint, {item_id: updates}, draft.payload.interaction)

    def _edit(self, user, draft, command, fingerprint, updates, interaction):
        items = {item.item_id: item for item in interaction.items}
        dependencies = {dep.item_id: dep for dep in interaction.dependencies}
        candidates = []
        try:
            for candidate in draft.payload.candidates:
                if candidate.id in updates:
                    if items[candidate.id].state in ('saved', 'discarded'):
                        raise _error('ITEM_NOT_EDITABLE', 409)
                    candidate, item, dependency = self._resolve(user, candidate, items[candidate.id],
                        updates=updates[candidate.id], increment=True)
                    items[candidate.id] = item
                    dependencies.pop(candidate.id, None)
                    if dependency:
                        dependencies[candidate.id] = dependency
                candidates.append(candidate)
            payload = self._payload(draft, candidates, items.values(), dependencies.values(), interaction=interaction)
        except (SmartEntryDomainError, MealDomainError) as error:
            raise _error(error.code) from None
        return self._execute(user, draft, command, fingerprint, payload)

    def confirm_items(self, user, draft_id, *, expected_version, key, selections,
                      accepted_estimates=(), timezone_name='UTC'):
        if not self.enabled:
            raise _error('INTERACTIVE_ENTRY_DISABLED', 409)
        command = _command(ConfirmItemsCommand, expected_version=expected_version, key=key,
                           selections=selections, accepted_estimates=accepted_estimates)
        canonical = lambda values: [dict(item_id=item, item_revision=revision) for item, revision in
                                   sorted({(value.item_id, value.item_revision) for value in values})]
        selected, accepted = canonical(command.selections), canonical(command.accepted_estimates)
        fingerprint = hashlib.sha256(json.dumps({'operation': 'confirm_items', 'draft_id': draft_id,
            'expected_version': expected_version, 'selections': selected, 'accepted_estimates': accepted,
            'timezone_name': timezone_name}, sort_keys=True, allow_nan=False).encode()).hexdigest()
        try:
            with self._mutation_scope(user):
                return self.repository.confirm_items(user, draft_id, expected_version=expected_version,
                    selections=selected, accepted_estimates=accepted, idempotency_key=key,
                    request_fingerprint=fingerprint, timezone_name=timezone_name)
        except SmartEntryRepositoryError as error:
            raise _repository_error(error) from None

    def resume(self, user, draft_id):
        draft = self._read(user, draft_id)
        return project_resumed_draft(draft, lambda catalog_id: self._food(user, catalog_id))


def project_resumed_draft(draft, food_lookup):
    """Build the current catalog-dependent view without changing stored food state."""
    items = {item.item_id: item for item in draft.payload.interaction.items}
    candidates = {candidate.id: candidate for candidate in draft.payload.candidates}
    for dependency in draft.payload.interaction.dependencies:
        food = food_lookup(dependency.catalog_id)
        if food is None or catalog_signature(food) != dependency.signature:
            item = items[dependency.item_id]
            if item.state in ('saved', 'discarded'):
                continue
            values = dict(item.values)
            sources = dict(item.sources)
            for field in ('calories', 'carbs', 'protein', 'fat'):
                values[field], sources[field] = None, 'unknown'
            item = replace(item, values=values, sources=sources, state='needs_clarification',
                missing_fields=tuple(dict.fromkeys((*item.missing_fields, 'calories', 'carbs', 'protein', 'fat'))))
            items[item.item_id] = item
            candidates[item.item_id] = replace(candidates[item.item_id], values=values)
    interaction = replace(draft.payload.interaction, items=tuple(items.values()))
    if any(item.state == 'needs_clarification' for item in interaction.items):
        interaction = replace(interaction, status='partially_saved'
            if any(item.state == 'saved' for item in interaction.items) else 'awaiting_clarification')
    return replace(draft, payload=replace(draft.payload, candidates=tuple(candidates.values()), interaction=interaction))
