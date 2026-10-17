from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from backend.application.ports.smart_entry_repository import (
    SmartEntryDraftPayload,
    SmartEntryRepositoryError,
)
from backend.domain.smart_entry import ResolvedCandidate
from backend.infrastructure.repositories.sqlite_smart_entry_repository import (
    SQLiteSmartEntryRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


def _database() -> tuple[SQLiteDatabase, Path]:
    path = Path("backend/data") / f"test-smart-entry-{uuid4().hex}.sqlite3"
    database = SQLiteDatabase(path)
    run_migrations(database, RECORDS_MIGRATIONS)
    return database, path


def _payload(
    *,
    log_date: str = "2026-07-26",
    raw_text: str = "早餐：燕麦 50g",
) -> SmartEntryDraftPayload:
    candidate = ResolvedCandidate(
        id="segment-1",
        kind="food",
        raw_text="燕麦 50g",
        normalized_text="燕麦 50g",
        subject_text="燕麦",
        meal_context="breakfast",
        selected=True,
        selected_catalog_id="food-oats",
        catalog_choices=(),
        issues=(),
        values={
            "name": "燕麦",
            "amount": 50,
            "unit": "g",
            "calories": 190,
            "carbs": 34,
            "protein": 6.5,
            "fat": 3.5,
        },
        provenance={"source": "public"},
    )
    return SmartEntryDraftPayload(
        log_date=log_date,
        raw_text=raw_text,
        parser_version="smart-entry-parser-v1",
        candidates=(candidate,),
    )


def _cleanup(path: Path) -> None:
    for suffix in ("", "-shm", "-wal"):
        target = Path(f"{path}{suffix}")
        if target.exists():
            target.unlink()


def test_legacy_interaction_projection_reads_without_writing_and_upgrades_on_update():
    import json
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = repository.create_draft('user-interaction', _payload(), expires_at='2099-01-01T00:00:00Z')
        with database.transaction() as connection:
            legacy = json.loads(connection.execute('SELECT payload_json FROM record_drafts WHERE id = ?', (draft.id,)).fetchone()[0])
            legacy.pop('interaction', None)
            connection.execute('UPDATE record_drafts SET schema_version = 1, payload_json = ? WHERE id = ?', (json.dumps(legacy), draft.id))
        before = path.read_bytes()
        projected = repository.get_draft('user-interaction', draft.id)
        assert path.read_bytes() == before
        assert projected.version == 1
        assert projected.payload.interaction.schema_version == 1
        assert projected.payload.interaction.items[0].item_id == 'segment-1'
        upgraded = repository.update_draft('user-interaction', draft.id, expected_version=1, payload=projected.payload)
        assert upgraded.payload.interaction.schema_version == 2
        assert upgraded.payload.interaction.active is False
        with database.connection() as connection:
            assert connection.execute('SELECT schema_version FROM record_drafts WHERE id = ?', (draft.id,)).fetchone()[0] == 2
        with pytest.raises(SmartEntryRepositoryError, match='DRAFT_VERSION_CONFLICT'):
            repository.update_draft('user-interaction', draft.id, expected_version=1, payload=projected.payload)
    finally:
        _cleanup(path)


@pytest.mark.parametrize('corruption', ['unknown_field', 'bad_rounds', 'wrong_id'])
def test_corrupt_persisted_interaction_is_rejected(corruption):
    import json
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = repository.create_draft('user-interaction', _payload(), expires_at='2099-01-01T00:00:00Z')
        with database.transaction() as connection:
            payload = json.loads(connection.execute('SELECT payload_json FROM record_drafts WHERE id = ?', (draft.id,)).fetchone()[0])
            if corruption == 'unknown_field':
                payload['interaction']['owner'] = 'client'
            elif corruption == 'bad_rounds':
                payload['interaction']['clarification_rounds'] = True
            else:
                payload['interaction']['items'][0]['item_id'] = 'different'
            connection.execute('UPDATE record_drafts SET payload_json = ? WHERE id = ?', (json.dumps(payload), draft.id))
        with pytest.raises(SmartEntryRepositoryError, match='SMART_ENTRY_DRAFT_CORRUPT'):
            repository.get_draft('user-interaction', draft.id)
    finally:
        _cleanup(path)


@pytest.mark.parametrize('corruption', ['values_list', 'provenance_list', 'payload_blob'])
def test_malformed_legacy_payload_shape_returns_bounded_corruption_error(corruption):
    import json
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = repository.create_draft('user-interaction', _payload(), expires_at='2099-01-01T00:00:00Z')
        with database.transaction() as connection:
            data = json.loads(connection.execute('SELECT payload_json FROM record_drafts WHERE id = ?', (draft.id,)).fetchone()[0])
            data.pop('interaction')
            if corruption == 'values_list':
                data['candidates'][0]['values'] = []
            elif corruption == 'provenance_list':
                data['candidates'][0]['provenance'] = []
            serialized = b'{}' if corruption == 'payload_blob' else json.dumps(data)
            connection.execute('UPDATE record_drafts SET schema_version = 1, payload_json = ? WHERE id = ?', (serialized, draft.id))
        with pytest.raises(SmartEntryRepositoryError, match='SMART_ENTRY_DRAFT_CORRUPT'):
            repository.get_draft('user-interaction', draft.id)
    finally:
        _cleanup(path)


def test_deeply_nested_legacy_json_returns_bounded_corruption_error():
    from backend.infrastructure.repositories.sqlite_smart_entry_repository import _draft

    row = {'payload_json': '[' * 20_000 + '0' + ']' * 20_000, 'agent_metadata_json': '{}'}
    with pytest.raises(SmartEntryRepositoryError, match='SMART_ENTRY_DRAFT_CORRUPT'):
        _draft(row)


def test_reordering_duplicate_food_names_preserves_item_ids_and_revisions():
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        first = _food_candidate('first', 'breakfast')
        second = _food_candidate('second', 'breakfast')
        payload = replace(_payload(), candidates=(first, second))
        draft = repository.create_draft('user-interaction', payload, expires_at='2099-01-01T00:00:00Z')
        updated = repository.update_draft('user-interaction', draft.id, expected_version=1, payload=replace(payload, candidates=(second, first), interaction=None))
        assert [(item.item_id, item.revision) for item in updated.payload.interaction.items] == [('second', 1), ('first', 1)]
        assert all(source == 'estimated' for item in updated.payload.interaction.items for source in item.sources.values())
    finally:
        _cleanup(path)


@pytest.mark.parametrize('change', ['erase', 'rewrite', 'catalog'])
def test_legacy_mutation_cannot_change_terminal_items(change):
    import json
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = repository.create_draft('user-interaction', _payload(), expires_at='2099-01-01T00:00:00Z')
        with database.transaction() as connection:
            data = json.loads(connection.execute('SELECT payload_json FROM record_drafts WHERE id = ?', (draft.id,)).fetchone()[0])
            data['interaction']['items'][0]['state'] = 'saved'
            connection.execute('UPDATE record_drafts SET payload_json = ? WHERE id = ?', (json.dumps(data), draft.id))
        payload = repository.get_draft('user-interaction', draft.id).payload
        if change == 'erase':
            candidates = (_cardio_candidate('workout'),)
        elif change == 'rewrite':
            candidates = (replace(payload.candidates[0], values={**payload.candidates[0].values, 'amount': 100}),)
        else:
            candidates = (replace(payload.candidates[0], selected_catalog_id='other-food'),)
        with pytest.raises(SmartEntryRepositoryError, match='ITEM_NOT_EDITABLE'):
            repository.update_draft('user-interaction', draft.id, expected_version=1, payload=replace(payload, candidates=candidates, interaction=None))
        assert repository.get_draft('user-interaction', draft.id).version == 1
    finally:
        _cleanup(path)


def _food_candidate(
    candidate_id: str,
    meal_context: str,
) -> ResolvedCandidate:
    return ResolvedCandidate(
        id=candidate_id,
        kind="food",
        raw_text="自制餐食 1份",
        normalized_text="自制餐食 1份",
        subject_text="自制餐食",
        meal_context=meal_context,
        selected=True,
        selected_catalog_id=None,
        catalog_choices=(),
        issues=(),
        values={
            "name": "自制餐食",
            "amount": 1,
            "unit": "serving",
            "basis_type": "per_serving",
            "calories": 300,
            "carbs": 40,
            "protein": 20,
            "fat": 8,
            "source": "agent_estimate",
            "is_estimate": True,
            "uncertainty": {"calories": {"min": 240, "max": 360}},
        },
        provenance={"source": "agent_estimate"},
        assumptions=("one serving",),
        agent_estimate_accepted=True,
    )


def _cardio_candidate(candidate_id: str) -> ResolvedCandidate:
    return ResolvedCandidate(
        id=candidate_id,
        kind="cardio",
        raw_text="跑步 30分钟",
        normalized_text="跑步 30分钟",
        subject_text="跑步",
        meal_context=None,
        selected=True,
        selected_catalog_id=None,
        catalog_choices=(),
        issues=(),
        values={
            "name": "跑步",
            "exercise_type": "cardio",
            "primary_muscle": "cardiovascular",
            "secondary_muscles": ("legs",),
            "duration_min": 30,
            "device_calories": None,
            "met": 8,
            "estimated_calories": 294,
            "is_estimate": True,
            "source": "user_custom",
        },
        provenance={"entry_method": "smart_entry"},
    )


def _strength_candidate(candidate_id: str) -> ResolvedCandidate:
    return ResolvedCandidate(
        id=candidate_id,
        kind="strength",
        raw_text="深蹲 3x8 60kg",
        normalized_text="深蹲 3x8 60kg",
        subject_text="深蹲",
        meal_context=None,
        selected=True,
        selected_catalog_id=None,
        catalog_choices=(),
        issues=(),
        values={
            "name": "深蹲",
            "exercise_type": "strength",
            "primary_muscle": "quadriceps",
            "secondary_muscles": ("glutes",),
            "set_count": 3,
            "reps": 8,
            "load_kg": 60,
            "bodyweight": False,
            "source": "user_custom",
        },
        provenance={"entry_method": "smart_entry"},
    )


def _confirmation_payload(
    candidates: tuple[ResolvedCandidate, ...],
) -> SmartEntryDraftPayload:
    return SmartEntryDraftPayload(
        log_date="2026-07-26",
        raw_text="mixed smart entry",
        parser_version="smart-entry-parser-v1",
        candidates=candidates,
    )


def test_smart_entry_drafts_are_owner_scoped_versioned_and_date_searchable():
    database, path = _database()
    now = datetime(2026, 7, 26, 8, tzinfo=timezone.utc)
    repository = SQLiteSmartEntryRepository(
        database,
        clock=lambda: now,
        id_factory=lambda: "smart-draft-1",
    )
    try:
        created = repository.create_draft(
            "user-a",
            _payload(),
            expires_at="2026-08-25T08:00:00Z",
        )

        assert created.version == 1
        assert created.agent_status == "not_requested"
        assert repository.get_draft("user-b", created.id) is None
        assert repository.find_latest_draft("user-a", "2026-07-26") == created

        updated = repository.update_draft(
            "user-a",
            created.id,
            expected_version=1,
            payload=_payload(raw_text="早餐：燕麦 60g"),
        )
        assert updated.version == 2
        assert updated.payload.raw_text == "早餐：燕麦 60g"

        with pytest.raises(SmartEntryRepositoryError) as raised:
            repository.update_draft(
                "user-a",
                created.id,
                expected_version=1,
                payload=_payload(),
            )
        assert raised.value.code == "DRAFT_VERSION_CONFLICT"

        repository.delete_draft("user-a", created.id)
        assert repository.get_draft("user-a", created.id) is None
    finally:
        _cleanup(path)


def test_smart_entry_draft_expiry_and_malformed_payload_are_defensive():
    database, path = _database()
    current = [datetime(2026, 7, 26, 8, tzinfo=timezone.utc)]
    repository = SQLiteSmartEntryRepository(
        database,
        clock=lambda: current[0],
        id_factory=lambda: "smart-draft-2",
    )
    try:
        created = repository.create_draft(
            "user-a",
            _payload(),
            expires_at="2026-07-27T08:00:00Z",
        )
        current[0] += timedelta(days=2)
        assert repository.get_draft("user-a", created.id) is None

        current[0] -= timedelta(days=2)
        with database.transaction() as connection:
            connection.execute(
                """
                UPDATE record_drafts
                SET payload_json = '{"unexpected":true}'
                WHERE id = ?
                """,
                (created.id,),
            )
        with pytest.raises(SmartEntryRepositoryError) as raised:
            repository.get_draft("user-a", created.id)
        assert raised.value.code == "SMART_ENTRY_DRAFT_CORRUPT"
    finally:
        _cleanup(path)


def test_smart_entry_draft_bounds_raw_text_and_candidate_count():
    database, path = _database()
    repository = SQLiteSmartEntryRepository(database)
    try:
        with pytest.raises(SmartEntryRepositoryError) as raised:
            repository.create_draft(
                "user-a",
                _payload(raw_text="x" * 10_001),
                expires_at="2099-01-01T00:00:00Z",
            )
        assert raised.value.code == "SMART_ENTRY_TEXT_INVALID"

        payload = _payload()
        with pytest.raises(SmartEntryRepositoryError) as raised:
            repository.create_draft(
                "user-a",
                SmartEntryDraftPayload(
                    log_date=payload.log_date,
                    raw_text=payload.raw_text,
                    parser_version=payload.parser_version,
                    candidates=payload.candidates * 101,
                ),
                expires_at="2099-01-01T00:00:00Z",
            )
        assert raised.value.code == "SMART_ENTRY_CANDIDATES_INVALID"
    finally:
        _cleanup(path)


def test_agent_state_writes_are_version_checked_and_preserve_failure_payload():
    database, path = _database()
    repository = SQLiteSmartEntryRepository(
        database,
        clock=lambda: datetime(2026, 7, 26, 8, tzinfo=timezone.utc),
        id_factory=lambda: "smart-draft-agent",
    )
    try:
        created = repository.create_draft(
            "user-a",
            _payload(),
            expires_at="2026-08-25T08:00:00Z",
        )
        failed = repository.mark_agent_failed(
            "user-a",
            created.id,
            expected_version=1,
            prompt_version="smart-entry-analysis-v1",
            model="model-a",
            metadata={"error_code": "MODEL_TIMEOUT"},
        )
        assert failed.version == 2
        assert failed.agent_status == "failed"
        assert failed.payload == created.payload

        completed = repository.save_analysis(
            "user-a",
            created.id,
            expected_version=2,
            payload=_payload(raw_text="早餐：燕麦 50g，已分析"),
            prompt_version="smart-entry-analysis-v1",
            model="model-b",
            metadata={"usage": {"total_tokens": 20}},
        )
        assert completed.version == 3
        assert completed.agent_status == "completed"
        assert completed.agent_model == "model-b"
        assert completed.agent_metadata["usage"]["total_tokens"] == 20

        with pytest.raises(SmartEntryRepositoryError) as raised:
            repository.save_analysis(
                "user-a",
                created.id,
                expected_version=2,
                payload=_payload(),
                prompt_version="smart-entry-analysis-v1",
                model="model-b",
                metadata={},
            )
        assert raised.value.code == "DRAFT_VERSION_CONFLICT"
    finally:
        _cleanup(path)


def test_confirmation_is_atomic_idempotent_and_raises_planned_meal_count():
    database, path = _database()
    repository = SQLiteSmartEntryRepository(
        database,
        clock=lambda: datetime(2026, 7, 26, 8, tzinfo=timezone.utc),
    )
    public_food = replace(
        _food_candidate("food-1", "breakfast"),
        selected_catalog_id="public-food",
        values={
            **_food_candidate("food-1", "breakfast").values,
            "source": "public",
            "is_estimate": False,
        },
        provenance={"source": "public", "license": "CC0-1.0"},
        agent_estimate_accepted=False,
    )
    payload = _confirmation_payload(
        (
            public_food,
            _food_candidate("food-2", "lunch"),
            _food_candidate("food-3", "dinner"),
            _food_candidate("food-4", "snack"),
            _strength_candidate("strength-1"),
            _cardio_candidate("cardio-1"),
        )
    )
    try:
        with database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO food_catalog (
                    id, owner_user_id, source, source_name, source_record_id,
                    dataset_version, name, basis_type, basis_amount, unit,
                    calories, carbs, protein, fat, license, attribution,
                    provenance_json, content_hash, active
                ) VALUES (
                    'public-food', NULL, 'public', 'test', 'public-food',
                    'v1', '自制餐食', 'per_serving', 1, 'serving',
                    300, 40, 20, 8, 'CC0-1.0', 'Test', '{}', 'hash', 1
                )
                """
            )
        draft = repository.create_draft(
            "user-a",
            payload,
            expires_at="2026-08-25T08:00:00Z",
        )
        confirmed = repository.confirm(
            "user-a",
            draft.id,
            expected_version=1,
            idempotency_key="key-1",
            request_fingerprint="fingerprint-1",
        )

        assert len(confirmed.meal_ids) == 4
        assert confirmed.training_session_id is not None
        assert repository.get_draft("user-a", draft.id) is None
        replayed = repository.confirm(
            "user-a",
            draft.id,
            expected_version=1,
            idempotency_key="key-1",
            request_fingerprint="fingerprint-1",
        )
        assert replayed.replayed is True
        assert replayed.meal_ids == confirmed.meal_ids
        with pytest.raises(SmartEntryRepositoryError) as raised:
            repository.confirm(
                "user-a",
                draft.id,
                expected_version=1,
                idempotency_key="key-1",
                request_fingerprint="different-fingerprint",
            )
        assert raised.value.code == "IDEMPOTENCY_KEY_REUSED"

        with database.connection() as connection:
            counts = {
                table: connection.execute(
                    f"SELECT COUNT(*) AS count FROM {table}"
                ).fetchone()["count"]
                for table in (
                    "meals",
                    "meal_items",
                    "training_sessions",
                    "strength_exercises",
                    "strength_sets",
                    "cardio_items",
                    "idempotency_keys",
                    "catalog_usage",
                )
            }
            planned = connection.execute(
                """
                SELECT planned_meal_count FROM daily_logs
                WHERE user_id = 'user-a' AND log_date = '2026-07-26'
                """
            ).fetchone()["planned_meal_count"]
        assert counts == {
            "meals": 4,
            "meal_items": 4,
            "training_sessions": 1,
            "strength_exercises": 1,
            "strength_sets": 3,
            "cardio_items": 1,
            "idempotency_keys": 1,
            "catalog_usage": 1,
        }
        assert planned == 4
    finally:
        _cleanup(path)


def test_late_confirmation_failure_rolls_back_every_formal_row():
    database, path = _database()
    ids = iter(
        (
            "draft-id",
            "daily-log-id",
            "session-id",
            "duplicate-cardio-id",
            "duplicate-cardio-id",
        )
    )
    repository = SQLiteSmartEntryRepository(
        database,
        clock=lambda: datetime(2026, 7, 26, 8, tzinfo=timezone.utc),
        id_factory=lambda: next(ids),
    )
    try:
        draft = repository.create_draft(
            "user-a",
            _confirmation_payload(
                (
                    _cardio_candidate("cardio-1"),
                    _cardio_candidate("cardio-2"),
                )
            ),
            expires_at="2026-08-25T08:00:00Z",
        )

        with pytest.raises(SmartEntryRepositoryError) as raised:
            repository.confirm(
                "user-a",
                draft.id,
                expected_version=1,
                idempotency_key="key-rollback",
                request_fingerprint="fingerprint-rollback",
            )
        assert raised.value.code == "SMART_ENTRY_CONFIRM_FAILED"

        with database.connection() as connection:
            assert all(
                connection.execute(
                    f"SELECT COUNT(*) AS count FROM {table}"
                ).fetchone()["count"]
                == 0
                for table in (
                    "daily_logs",
                    "training_sessions",
                    "cardio_items",
                    "idempotency_keys",
                )
            )
        assert repository.get_draft("user-a", draft.id) is not None
    finally:
        _cleanup(path)


def test_confirmation_rejects_unaccepted_agent_estimates_before_writing():
    database, path = _database()
    repository = SQLiteSmartEntryRepository(
        database,
        clock=lambda: datetime(2026, 7, 26, 8, tzinfo=timezone.utc),
    )
    candidate = replace(
        _food_candidate("food-agent", "breakfast"),
        agent_estimate_accepted=False,
    )
    try:
        draft = repository.create_draft(
            "user-a",
            _confirmation_payload((candidate,)),
            expires_at="2026-08-25T08:00:00Z",
        )
        with pytest.raises(SmartEntryRepositoryError) as raised:
            repository.confirm(
                "user-a",
                draft.id,
                expected_version=1,
                idempotency_key="key-unaccepted",
                request_fingerprint="fingerprint-unaccepted",
            )
        assert (
            raised.value.code
            == "SMART_ENTRY_AGENT_ESTIMATE_NOT_ACCEPTED"
        )
        with database.connection() as connection:
            assert connection.execute(
                "SELECT COUNT(*) AS count FROM meals"
            ).fetchone()["count"] == 0
    finally:
        _cleanup(path)


def test_confirmation_rejects_cardio_without_device_calories_or_met():
    database, path = _database()
    repository = SQLiteSmartEntryRepository(
        database,
        clock=lambda: datetime(2026, 7, 26, 8, tzinfo=timezone.utc),
    )
    candidate = replace(
        _cardio_candidate("cardio-no-energy"),
        values={
            **_cardio_candidate("cardio-no-energy").values,
            "device_calories": None,
            "met": None,
            "estimated_calories": None,
        },
    )
    try:
        draft = repository.create_draft(
            "user-a",
            _confirmation_payload((candidate,)),
            expires_at="2026-08-25T08:00:00Z",
        )

        with pytest.raises(SmartEntryRepositoryError) as raised:
            repository.confirm(
                "user-a",
                draft.id,
                expected_version=1,
                idempotency_key="key-cardio-energy",
                request_fingerprint="fingerprint-cardio-energy",
            )

        assert raised.value.code == "SMART_ENTRY_DRAFT_INCOMPLETE"
        with database.connection() as connection:
            assert connection.execute(
                "SELECT COUNT(*) AS count FROM training_sessions"
            ).fetchone()["count"] == 0
        assert repository.get_draft("user-a", draft.id) is not None
    finally:
        _cleanup(path)
