import pytest

from backend.domain.entry_interaction import EntryInteraction, EntryQuestion, EntryQuestionGroup


@pytest.mark.parametrize('item_id,field', [(123, 'amount'), ('item', 7), (' ', 'amount'), ('item', 'status')])
def test_question_targets_require_known_field_and_nonblank_item_id(item_id, field):
    with pytest.raises(ValueError, match='QUESTION_INVALID'):
        EntryQuestion(item_id, field)


@pytest.mark.parametrize('rounds', [1, 2])
def test_round_counter_requires_committed_question_groups(rounds):
    with pytest.raises(ValueError, match='QUESTION_ROUNDS_INVALID'):
        EntryInteraction(clarification_rounds=rounds)


@pytest.mark.parametrize('asked_at', ['2026-10-15', 'not-a-date', '2026-10-15T10:00:00'])
def test_question_group_requires_aware_timestamp(asked_at):
    with pytest.raises(ValueError, match='QUESTION_GROUP_TIMESTAMP_INVALID'):
        EntryQuestionGroup('group', asked_at, 2, (EntryQuestion('item', 'amount'),))
