from __future__ import annotations

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import sqlite3

import pytest

from backend.application.ports.meal_repository import (
    CustomFoodSnapshot,
    MealDraftInput,
    MealDraftItemInput,
    MealRepositoryError,
)
from backend.infrastructure.repositories.sqlite_meal_repository import (
    SQLiteMealRepository,
)
from backend.infrastructure.repositories.sqlite_food_catalog_repository import (
    SQLiteFoodCatalogRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def _database(tmp_path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "meals.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    return database


def _repository(tmp_path) -> SQLiteMealRepository:
    return SQLiteMealRepository(
        _database(tmp_path),
        clock=lambda: NOW,
        id_factory=iter(("draft-1",)).__next__,
    )


def _custom_payload(*, name: str = "Lunch") -> MealDraftInput:
    return MealDraftInput(
        log_date="2026-07-24",
        name=name,
        meal_type="lunch",
        entry_method="form",
        items=(
            MealDraftItemInput(
                amount=150,
                unit="g",
                custom_food=CustomFoodSnapshot(
                    name="Tofu",
                    basis_type="per_100g",
                    basis_amount=100,
                    unit="g",
                    calories=80,
                    carbs=2,
                    protein=8,
                    fat=4,
                ),
            ),
        ),
    )


def test_create_get_update_and_delete_owned_draft(tmp_path):
    repository = _repository(tmp_path)

    created = repository.create_draft(
        "user-a",
        _custom_payload(),
        expires_at="2026-08-23T12:00:00Z",
    )

    assert created.id == "draft-1"
    assert created.user_id == "user-a"
    assert created.version == 1
    assert created.payload.items[0].food_name == "Tofu"
    assert created.payload.items[0].calories == 120
    assert repository.get_draft("user-a", created.id) == created

    updated = repository.update_draft(
        "user-a",
        created.id,
        expected_version=1,
        payload=_custom_payload(name="Updated lunch"),
    )

    assert updated.version == 2
    assert updated.payload.name == "Updated lunch"

    repository.delete_draft("user-a", created.id)

    assert repository.get_draft("user-a", created.id) is None


def test_draft_owner_isolation_and_optimistic_version_conflict(tmp_path):
    repository = _repository(tmp_path)
    created = repository.create_draft(
        "user-a",
        _custom_payload(),
        expires_at="2026-08-23T12:00:00Z",
    )

    assert repository.get_draft("user-b", created.id) is None
    with pytest.raises(MealRepositoryError) as foreign:
        repository.update_draft(
            "user-b",
            created.id,
            expected_version=1,
            payload=_custom_payload(),
        )
    assert foreign.value.code == "DRAFT_NOT_FOUND"
    with pytest.raises(MealRepositoryError) as foreign_delete:
        repository.delete_draft("user-b", created.id)
    assert foreign_delete.value.code == "DRAFT_NOT_FOUND"
    assert repository.get_draft("user-a", created.id) == created

    repository.update_draft(
        "user-a",
        created.id,
        expected_version=1,
        payload=_custom_payload(name="Version two"),
    )
    with pytest.raises(MealRepositoryError) as stale:
        repository.update_draft(
            "user-a",
            created.id,
            expected_version=1,
            payload=_custom_payload(name="Stale"),
        )
    assert stale.value.code == "DRAFT_VERSION_CONFLICT"

    invalid = _custom_payload()
    invalid_custom = invalid.items[0].custom_food
    invalid_payload = MealDraftInput(
        log_date=invalid.log_date,
        name=invalid.name,
        meal_type=invalid.meal_type,
        entry_method=invalid.entry_method,
        items=(
            MealDraftItemInput(
                amount=100,
                unit="g",
                custom_food=CustomFoodSnapshot(
                    name=invalid_custom.name,
                    basis_type=invalid_custom.basis_type,
                    basis_amount=invalid_custom.basis_amount,
                    unit=invalid_custom.unit,
                    calories=None,
                    carbs=1,
                    protein=1,
                    fat=1,
                ),
            ),
        ),
    )
    with pytest.raises(MealRepositoryError) as stale_invalid:
        repository.update_draft(
            "user-a",
            created.id,
            expected_version=1,
            payload=invalid_payload,
        )
    assert stale_invalid.value.code == "DRAFT_VERSION_CONFLICT"


def test_expired_draft_is_hidden_and_cannot_be_updated(tmp_path):
    database = _database(tmp_path)
    active = SQLiteMealRepository(
        database,
        clock=lambda: NOW,
        id_factory=iter(("draft-1",)).__next__,
    )
    active.create_draft(
        "user-a",
        _custom_payload(),
        expires_at="2026-07-25T12:00:00Z",
    )
    expired = SQLiteMealRepository(
        database,
        clock=lambda: NOW + timedelta(days=2),
    )

    assert expired.get_draft("user-a", "draft-1") is None
    with pytest.raises(MealRepositoryError) as captured:
        expired.update_draft(
            "user-a",
            "draft-1",
            expected_version=1,
            payload=_custom_payload(),
        )
    assert captured.value.code == "DRAFT_EXPIRED"


def test_expiry_is_compared_as_an_instant_and_stored_in_canonical_utc(tmp_path):
    database = _database(tmp_path)
    repository = SQLiteMealRepository(database, clock=lambda: NOW)

    with pytest.raises(MealRepositoryError) as past:
        repository.create_draft(
            "user-a",
            _custom_payload(),
            expires_at="2026-07-24T13:00:00+05:00",
        )
    assert past.value.code == "DRAFT_EXPIRY_INVALID"

    created = repository.create_draft(
        "user-a",
        _custom_payload(),
        expires_at="2026-07-25T17:00:00+05:00",
    )
    assert created.expires_at == "2026-07-25T12:00:00Z"


def test_catalog_food_values_are_server_resolved_and_snapshotted(tmp_path):
    database = _database(tmp_path)
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO food_catalog (
                id, owner_user_id, source, source_name, source_record_id,
                name, basis_type, basis_amount, unit, calories, carbs,
                protein, fat, license, attribution, provenance_json
            ) VALUES (
                'rice', NULL, 'public', 'USDA FoodData Central', 'rice-1',
                'Cooked rice', 'per_100g', 100, 'g', 116, 25.9, 2.6, 0.3,
                'CC0-1.0', 'USDA FoodData Central', '{"audited":true}'
            )
            """
        )
    repository = SQLiteMealRepository(
        database,
        clock=lambda: NOW,
    )
    payload = MealDraftInput(
        log_date="2026-07-24",
        name="Lunch",
        meal_type="lunch",
        entry_method="form",
        items=(
            MealDraftItemInput(
                catalog_food_id="rice",
                amount=150,
                unit="g",
            ),
        ),
    )

    draft = repository.create_draft(
        "user-a",
        payload,
        expires_at="2026-08-23T12:00:00Z",
    )
    with database.transaction() as connection:
        connection.execute(
            "UPDATE food_catalog SET calories = 999 WHERE id = 'rice'"
        )

    stored = repository.get_draft("user-a", draft.id)
    assert stored.payload.items[0].calories == 174
    assert stored.payload.items[0].provenance["license"] == "CC0-1.0"
    confirmed = repository.confirm(
        "user-a",
        draft.id,
        expected_version=1,
        idempotency_key="snapshot-key",
        request_fingerprint="snapshot",
    )
    assert confirmed.items[0].calories == 174
    with database.transaction() as connection:
        connection.execute(
            "UPDATE food_catalog SET calories = 500 WHERE id = 'rice'"
        )
    assert repository.list_meals(
        "user-a",
        "2026-07-24",
    )[0].items[0].calories == 174


def test_incomplete_custom_food_cannot_enter_a_draft(tmp_path):
    repository = _repository(tmp_path)
    invalid = _custom_payload()
    invalid_custom = invalid.items[0].custom_food
    payload = MealDraftInput(
        log_date=invalid.log_date,
        name=invalid.name,
        meal_type=invalid.meal_type,
        entry_method=invalid.entry_method,
        items=(
            MealDraftItemInput(
                amount=100,
                unit="g",
                custom_food=CustomFoodSnapshot(
                    name=invalid_custom.name,
                    basis_type=invalid_custom.basis_type,
                    basis_amount=invalid_custom.basis_amount,
                    unit=invalid_custom.unit,
                    calories=None,
                    carbs=invalid_custom.carbs,
                    protein=invalid_custom.protein,
                    fat=invalid_custom.fat,
                ),
            ),
        ),
    )

    with pytest.raises(MealRepositoryError) as captured:
        repository.create_draft(
            "user-a",
            payload,
            expires_at="2026-08-23T12:00:00Z",
        )

    assert captured.value.code == "FOOD_NUTRIENT_INVALID"


def test_confirm_atomically_creates_meal_items_custom_food_and_usage(tmp_path):
    database = _database(tmp_path)
    _insert_public_rice(database)
    repository = SQLiteMealRepository(database, clock=lambda: NOW)
    payload = MealDraftInput(
        log_date="2026-07-24",
        name="Lunch",
        meal_type="lunch",
        entry_method="form",
        items=(
            MealDraftItemInput(
                catalog_food_id="rice",
                amount=150,
                unit="g",
            ),
            _custom_payload().items[0],
        ),
    )
    draft = repository.create_draft(
        "user-a",
        payload,
        expires_at="2026-08-23T12:00:00Z",
    )

    confirmed = repository.confirm(
        "user-a",
        draft.id,
        expected_version=draft.version,
        idempotency_key="confirm-1",
        request_fingerprint="fingerprint-1",
    )

    assert confirmed.replayed is False
    assert len(confirmed.items) == 2
    assert confirmed.items[0].calories == 174
    assert confirmed.items[1].food_name == "Tofu"
    assert confirmed.items[1].catalog_food_id is not None
    assert repository.get_draft("user-a", draft.id) is None
    assert repository.list_meals("user-a", "2026-07-24") == (confirmed,)
    with database.connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM daily_logs"
        ).fetchone()["count"] == 1
        assert connection.execute(
            """
            SELECT COUNT(*) AS count FROM food_catalog
            WHERE owner_user_id = 'user-a' AND source = 'user_custom'
            """
        ).fetchone()["count"] == 1
        assert connection.execute(
            """
            SELECT COUNT(*) AS count FROM catalog_usage
            WHERE user_id = 'user-a'
            """
        ).fetchone()["count"] == 2


def test_confirmed_custom_food_uses_catalog_normalization_and_chinese_index(tmp_path):
    database = _database(tmp_path)
    repository = SQLiteMealRepository(database, clock=lambda: NOW)
    payload = MealDraftInput(
        log_date="2026-07-24",
        name="Lunch",
        meal_type="lunch",
        entry_method="form",
        items=(
            MealDraftItemInput(
                amount=100,
                unit="g",
                custom_food=CustomFoodSnapshot(
                    name="  香喷喷白米饭碗  ",
                    basis_type="per_100g",
                    basis_amount=100,
                    unit="g",
                    calories=150,
                    carbs=30,
                    protein=4,
                    fat=2,
                ),
            ),
        ),
    )
    draft = repository.create_draft(
        "user-a",
        payload,
        expires_at="2026-08-23T12:00:00Z",
    )

    confirmed = repository.confirm(
        "user-a",
        draft.id,
        expected_version=1,
        idempotency_key="custom-search",
        request_fingerprint="custom-search",
    )

    assert confirmed.items[0].food_name == "香喷喷白米饭碗"
    results = SQLiteFoodCatalogRepository(database).search(
        "user-a",
        "白米饭",
        limit=20,
    )
    assert [item.id for item in results] == [
        confirmed.items[0].catalog_food_id
    ]


def test_confirm_replays_matching_key_and_rejects_fingerprint_reuse(tmp_path):
    repository = SQLiteMealRepository(_database(tmp_path), clock=lambda: NOW)
    draft = repository.create_draft(
        "user-a",
        _custom_payload(),
        expires_at="2026-08-23T12:00:00Z",
    )
    first = repository.confirm(
        "user-a",
        draft.id,
        expected_version=1,
        idempotency_key="same-key",
        request_fingerprint="same-fingerprint",
    )

    replay = repository.confirm(
        "user-a",
        draft.id,
        expected_version=1,
        idempotency_key="same-key",
        request_fingerprint="same-fingerprint",
    )

    assert replay.id == first.id
    assert replay.items == first.items
    assert replay.replayed is True
    assert len(repository.list_meals("user-a", "2026-07-24")) == 1
    with pytest.raises(MealRepositoryError) as captured:
        repository.confirm(
            "user-a",
            draft.id,
            expected_version=1,
            idempotency_key="same-key",
            request_fingerprint="different",
        )
    assert captured.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_confirm_rejects_empty_and_stale_drafts(tmp_path):
    repository = SQLiteMealRepository(_database(tmp_path), clock=lambda: NOW)
    empty_payload = MealDraftInput(
        log_date="2026-07-24",
        name="Lunch",
        meal_type="lunch",
        entry_method="form",
        items=(),
    )
    empty = repository.create_draft(
        "user-a",
        empty_payload,
        expires_at="2026-08-23T12:00:00Z",
    )
    with pytest.raises(MealRepositoryError) as incomplete:
        repository.confirm(
            "user-a",
            empty.id,
            expected_version=1,
            idempotency_key="empty-key",
            request_fingerprint="empty",
        )
    assert incomplete.value.code == "DRAFT_INCOMPLETE"

    updated = repository.update_draft(
        "user-a",
        empty.id,
        expected_version=1,
        payload=_custom_payload(),
    )
    with pytest.raises(MealRepositoryError) as stale:
        repository.confirm(
            "user-a",
            updated.id,
            expected_version=1,
            idempotency_key="stale-key",
            request_fingerprint="stale",
        )
    assert stale.value.code == "DRAFT_VERSION_CONFLICT"


def test_confirm_rolls_back_every_write_when_item_insert_fails(tmp_path):
    database = _database(tmp_path)
    repository = SQLiteMealRepository(database, clock=lambda: NOW)
    draft = repository.create_draft(
        "user-a",
        _custom_payload(),
        expires_at="2026-08-23T12:00:00Z",
    )
    with database.transaction() as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_meal_item
            BEFORE INSERT ON meal_items
            BEGIN
                SELECT RAISE(ABORT, 'simulated item failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        repository.confirm(
            "user-a",
            draft.id,
            expected_version=1,
            idempotency_key="rollback-key",
            request_fingerprint="rollback",
        )

    assert repository.get_draft("user-a", draft.id) == draft
    with database.connection() as connection:
        for table in (
            "daily_logs",
            "meals",
            "meal_items",
            "catalog_usage",
            "idempotency_keys",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) AS count FROM {table}"
            ).fetchone()["count"] == 0
        assert connection.execute(
            """
            SELECT COUNT(*) AS count FROM food_catalog
            WHERE owner_user_id = 'user-a'
            """
        ).fetchone()["count"] == 0


def test_concurrent_confirm_retries_create_one_meal(tmp_path):
    database = _database(tmp_path)
    setup = SQLiteMealRepository(database, clock=lambda: NOW)
    draft = setup.create_draft(
        "user-a",
        _custom_payload(),
        expires_at="2026-08-23T12:00:00Z",
    )

    def confirm():
        return SQLiteMealRepository(database, clock=lambda: NOW).confirm(
            "user-a",
            draft.id,
            expected_version=1,
            idempotency_key="concurrent-key",
            request_fingerprint="concurrent",
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: confirm(), range(4)))

    assert {result.id for result in results} == {results[0].id}
    assert len(setup.list_meals("user-a", "2026-07-24")) == 1


def test_confirm_reads_expiry_clock_after_acquiring_write_lock(tmp_path):
    database = _database(tmp_path)
    setup = SQLiteMealRepository(database, clock=lambda: NOW)
    draft = setup.create_draft(
        "user-a",
        _custom_payload(),
        expires_at="2026-08-23T12:00:00Z",
    )
    tracking = _LockTrackingDatabase(database.path)

    def locked_clock():
        assert tracking.lock_acquired
        return NOW

    confirmed = SQLiteMealRepository(
        tracking,
        clock=locked_clock,
    ).confirm(
        "user-a",
        draft.id,
        expected_version=1,
        idempotency_key="locked-clock",
        request_fingerprint="locked-clock",
    )

    assert confirmed.id is not None


def _insert_public_rice(database: SQLiteDatabase) -> None:
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO food_catalog (
                id, owner_user_id, source, source_name, source_record_id,
                name, basis_type, basis_amount, unit, calories, carbs,
                protein, fat, license, attribution, provenance_json
            ) VALUES (
                'rice', NULL, 'public', 'USDA FoodData Central', 'rice-1',
                'Cooked rice', 'per_100g', 100, 'g', 116, 25.9, 2.6, 0.3,
                'CC0-1.0', 'USDA FoodData Central', '{"audited":true}'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO catalog_search (
                catalog_kind, catalog_id, name, aliases, pinyin, source_tokens
            ) VALUES ('food', 'rice', 'Cooked rice', '', '', 'rice')
            """
        )


class _LockTrackingDatabase(SQLiteDatabase):
    def __init__(self, path):
        super().__init__(path)
        self.lock_acquired = False

    @contextmanager
    def transaction(self):
        with super().transaction() as connection:
            self.lock_acquired = True
            try:
                yield connection
            finally:
                self.lock_acquired = False
