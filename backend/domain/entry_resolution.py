"""Deterministic food-item resolution; no persistence or model access."""
from dataclasses import replace
import hashlib
import json
import math
from decimal import Decimal

from backend.domain.entry_interaction import EntryItem, catalog_portion
from backend.domain.meals import FoodDefinition, FoodPortion, MealDomainError
from backend.domain.smart_entry import SmartEntryDomainError

NUTRIENTS = ('calories', 'carbs', 'protein', 'fat')
REQUIRED = ('name', 'amount', 'unit', 'basis_type', *NUTRIENTS)
WRITABLE = frozenset((*REQUIRED, 'selected_catalog_id', 'intake_ratio'))


def consumed_amount(item: EntryItem) -> float:
    """Stored amount is observed; formal records use this consumed amount once.

    Catalog nutrient totals are already scaled. Explicit manual nutrients are
    user-declared consumed totals and must not be scaled a second time.
    """
    amount = item.values.get('amount')
    ratio = item.values.get('intake_ratio')
    ratio = 1 if ratio is None else ratio
    validate_updates({'amount': amount, 'intake_ratio': ratio})
    if amount is None:
        raise SmartEntryDomainError('FOOD_PORTION_AMOUNT_INVALID')
    consumed = float(Decimal(str(amount)) * Decimal(str(ratio)))
    if not math.isfinite(consumed) or consumed <= 0:
        raise SmartEntryDomainError('FOOD_PORTION_SCALE_INVALID')
    return consumed


def catalog_signature(food) -> str:
    """Hash content and provenance actually used by portion resolution."""
    fields = ('id', 'name', 'basis_type', 'basis_amount', 'unit', *NUTRIENTS,
              'source', 'content_hash', 'dataset_version', 'active')
    content = {key: getattr(food, key) for key in fields}
    for key in ('basis_amount', *NUTRIENTS):
        content[key] = float(content[key])
    content['active'] = bool(content['active'])
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def validate_updates(updates: dict) -> None:
    if not isinstance(updates, dict) or set(updates) - WRITABLE:
        raise SmartEntryDomainError('ENTRY_FIELDS_INVALID')
    for key, value in updates.items():
        if value is None:
            continue
        if key in ('amount', 'intake_ratio', *NUTRIENTS):
            try:
                finite = type(value) in (float, int) and math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise SmartEntryDomainError('ENTRY_VALUE_INVALID')
            if key == 'amount' and value <= 0 or key in NUTRIENTS and value < 0:
                raise SmartEntryDomainError('ENTRY_VALUE_INVALID')
            if key == 'intake_ratio' and not 0 < value <= 1:
                raise SmartEntryDomainError('INTAKE_RATIO_INVALID')
        elif not isinstance(value, str) or not value.strip():
            raise SmartEntryDomainError('ENTRY_VALUE_INVALID')
    if updates.get('basis_type') not in (None, 'per_100g', 'per_100ml', 'per_serving'):
        raise SmartEntryDomainError('FOOD_BASIS_TYPE_INVALID')


def resolve_item(item: EntryItem, food=None, *, updates=None, increment=False) -> EntryItem:
    if item.state in ('saved', 'discarded'):
        if updates:
            raise SmartEntryDomainError('ITEM_NOT_EDITABLE')
        return item
    updates = updates or {}
    validate_updates(updates)
    values = {**item.values, **updates}
    validate_updates({key: value for key, value in values.items() if key in WRITABLE})
    sources = {**item.sources, **{key: 'user_provided' for key in updates}}
    if food is not None:
        values.update(name=food.name, basis_type=food.basis_type)
        sources.update(name='estimated' if item.sources.get('name') == 'estimated'
                       and 'name' not in updates else 'catalog', basis_type='catalog')
        if values.get('amount') is not None and values.get('unit') is not None:
            definition = FoodDefinition(**{key: getattr(food, key) for key in
                ('name', 'basis_type', 'basis_amount', 'unit', *NUTRIENTS, 'source')})
            try:
                portion = catalog_portion(definition, amount=values['amount'], unit=values['unit'],
                                          intake_ratio=1 if values.get('intake_ratio') is None else values['intake_ratio'])
            except MealDomainError:
                values['unit'] = None
                sources['unit'] = 'unknown'
                for key in NUTRIENTS:
                    values[key] = None
                    sources[key] = 'unknown'
            else:
                for key in NUTRIENTS:
                    values[key] = getattr(portion, key)
                    sources[key] = 'catalog'
                estimated = any(sources.get(key) == 'estimated' for key in ('name', 'amount', 'unit', 'intake_ratio'))
                values.update(source=food.source, is_estimate=estimated)
                sources.update(source='catalog', is_estimate='catalog')
        else:
            for key in NUTRIENTS:
                values[key] = None
                sources[key] = 'unknown'
    missing = tuple(key for key in REQUIRED if values.get(key) is None or values.get(key) == '')
    if food is None and all(sources.get(key) == 'user_provided' for key in NUTRIENTS):
        values['source'], sources['source'] = 'user_custom', 'user_provided'
    if not missing:
        # Manual nutrition is the user's consumed total; catalog totals are scaled above.
        FoodPortion(values['name'], values['amount'], values['unit'], values['basis_type'],
                    *(values[key] for key in NUTRIENTS), values.get('source', 'user_custom'))
        consumed_amount(replace(item, values=values, sources=sources))
    return replace(item, values=values, sources=sources, missing_fields=missing,
                   state='ready' if not missing else 'needs_clarification',
                   revision=item.revision + int(increment))
