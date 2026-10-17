import pytest

from backend.domain.entry_interaction import EntryItem, replace_fields


def test_correction_preserves_identity_and_estimated_original():
    original = EntryItem('food-1', 1, 'ready', {'amount_g': 100},
                         {'amount_g': 'estimated'}, (), ('catalog portion 100g',))
    corrected = replace_fields(original, {'amount_g': 150}, {'amount_g': 'user_provided'})
    assert corrected.item_id == original.item_id
    assert corrected.revision == 2
    assert corrected.state == 'needs_clarification'
    assert corrected.values == {'amount_g': 150}
    assert original.values == {'amount_g': 100}
    assert original.sources == {'amount_g': 'estimated'}


@pytest.mark.parametrize('state', ['saved', 'discarded'])
def test_terminal_items_cannot_be_corrected(state):
    with pytest.raises(ValueError, match='ITEM_NOT_EDITABLE'):
        replace_fields(EntryItem('a', 1, state, {}, {}, (), ()), {}, {})


def test_each_updated_field_requires_a_source():
    with pytest.raises(ValueError, match='FIELD_SOURCE_REQUIRED'):
        replace_fields(EntryItem('a', 1, 'ready', {}, {}, (), ()), {'amount': 1}, {})


def test_duplicate_names_keep_ids_after_reordering_and_acceptance_keeps_estimates():
    from dataclasses import replace
    from backend.domain.entry_interaction import project_interaction
    from backend.domain.smart_entry import ResolvedCandidate

    first = ResolvedCandidate('a', 'food', 'rice', 'rice', 'rice', None,
                              True, None, (), (), {'name': 'rice', 'calories': 100,
                              'is_estimate': True}, {}, (), True)
    second = replace(first, id='b', values={'name': 'rice', 'calories': 200})
    projected = project_interaction((second, first))
    assert projected.schema_version == 1
    assert projected.clarification_rounds == 0
    assert [item.item_id for item in projected.items] == ['b', 'a']
    assert projected.items[1].sources['calories'] == 'estimated'
    assert projected.items[0].sources['calories'] == 'unknown'
    assert all(item.revision == 1 for item in projected.items)
    assert project_interaction((replace(first, kind='cardio'),)).items == ()


def test_new_unmatched_item_requires_manual_nutrition():
    from backend.domain.entry_interaction import food_entry_item
    from backend.domain.smart_entry import ResolvedCandidate

    candidate = ResolvedCandidate('a', 'food', 'rice', 'rice', 'rice', None,
                                  True, None, (), (), {'calories': 999,
                                  'source': 'agent_estimate'}, {}, (), True)
    item = food_entry_item(candidate)
    assert item.item_id == 'a'
    assert item.values['calories'] is None
    assert item.sources['calories'] == 'unknown'
    assert set(('calories', 'carbs', 'protein', 'fat')) <= set(item.missing_fields)


def test_catalog_portion_scales_by_intake_ratio():
    from backend.domain.entry_interaction import catalog_portion
    from backend.domain.meals import FoodDefinition

    food = FoodDefinition('rice', 'per_100g', 100, 'g', 200, 40, 4, 2, 'public')
    portion = catalog_portion(food, amount=150, unit='g', intake_ratio=0.5)
    assert portion.amount == 75
    assert (portion.calories, portion.carbs, portion.protein, portion.fat) == (150, 30, 3, 1.5)
    for invalid in (-0.1, 0, 1.1, float('nan'), True):
        with pytest.raises(ValueError, match='INTAKE_RATIO_INVALID'):
            catalog_portion(food, amount=150, unit='g', intake_ratio=invalid)
    with pytest.raises(ValueError, match='FOOD_UNIT_INCOMPATIBLE'):
        catalog_portion(food, amount=150, unit='ml', intake_ratio=1)


def test_intake_ratio_preserves_decimal_half_up_rounding_boundary():
    from backend.domain.entry_interaction import catalog_portion
    from backend.domain.meals import FoodDefinition

    food = FoodDefinition('portion', 'per_serving', 1, 'serving', 1, 1, 1, 1, 'public')
    portion = catalog_portion(food, amount=1.5, unit='serving', intake_ratio=0.3)
    assert portion.amount == 0.45
    assert (portion.calories, portion.carbs, portion.protein, portion.fat) == (0.5, 0.5, 0.5, 0.5)


@pytest.mark.parametrize('revision', [0, -1, True, 1.5])
def test_item_rejects_invalid_revisions(revision):
    with pytest.raises(ValueError, match='ITEM_REVISION_INVALID'):
        EntryItem('a', revision, 'ready', {}, {}, (), ())


def test_closed_item_contract_and_duplicate_ids():
    from backend.domain.entry_interaction import EntryInteraction

    for identity in ('', ' '):
        with pytest.raises(ValueError, match='ITEM_ID_INVALID'):
            EntryItem(identity, 1, 'ready', {}, {}, (), ())
    with pytest.raises(ValueError, match='ITEM_STATE_INVALID'):
        EntryItem('a', 1, 'bogus', {}, {}, (), ())
    with pytest.raises(ValueError, match='FIELD_SOURCE_INVALID'):
        EntryItem('a', 1, 'ready', {'x': 1}, {'x': 'bogus'}, (), ())
    item = EntryItem('a', 1, 'ready', {}, {}, (), ())
    with pytest.raises(ValueError, match='ITEM_ID_DUPLICATE'):
        EntryInteraction(items=(item, item))
    for schema in (True, 0, 3, 1.0):
        with pytest.raises(ValueError, match='INTERACTION_SCHEMA_INVALID'):
            EntryInteraction(schema_version=schema)
    for rounds in (True, -1, 1.5):
        with pytest.raises(ValueError, match='CLARIFICATION_ROUNDS_INVALID'):
            EntryInteraction(clarification_rounds=rounds)


def test_constructor_and_replacement_copy_nested_values():
    values = {'nested': {'x': 1}}
    item = EntryItem('a', 1, 'ready', values, {'nested': 'unknown'}, (), ())
    values['nested']['x'] = 2
    assert item.values['nested']['x'] == 1
    updated = replace_fields(item, {}, {})
    updated.values['nested']['x'] = 3
    assert item.values['nested']['x'] == 1
