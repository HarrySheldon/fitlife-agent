from __future__ import annotations

import pytest

from backend.application.ports.exercise_catalog_repository import (
    ExerciseCatalogRepositoryError,
    ExerciseDefinition,
    NewCustomExercise,
)
from backend.infrastructure.repositories.sqlite_exercise_catalog_repository import (
    SQLiteExerciseCatalogRepository,
)
from backend.infrastructure.repositories.sqlite_food_catalog_repository import (
    _source_tokens,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


def _database(tmp_path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "exercise-catalog.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    return database


def _insert_exercise(
    database: SQLiteDatabase,
    *,
    exercise_id: str,
    owner_user_id: str | None,
    name: str,
    active: bool = True,
    aliases: tuple[str, ...] = (),
) -> None:
    source = "public" if owner_user_id is None else "user_custom"
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO exercise_catalog (
                id, owner_user_id, source, source_name, source_record_id,
                dataset_version, name, exercise_type, primary_muscle,
                secondary_muscles_json, met, license, attribution,
                provenance_json, content_hash, active
            ) VALUES (
                ?, ?, ?, 'test-catalog', ?, 'test-v1', ?, 'strength',
                'quadriceps', '["glutes"]', NULL, 'Unlicense',
                'Test catalog', '{}', ?, ?
            )
            """,
            (
                exercise_id,
                owner_user_id,
                source,
                exercise_id,
                name,
                f"hash-{exercise_id}",
                int(active),
            ),
        )
        connection.execute(
            """
            INSERT INTO catalog_search (
                catalog_kind, catalog_id, name, aliases, pinyin, source_tokens
            ) VALUES ('exercise', ?, ?, ?, '', ?)
            """,
            (
                exercise_id,
                name,
                " ".join(aliases),
                _source_tokens(name, aliases, ""),
            ),
        )
        for index, alias in enumerate(aliases):
            connection.execute(
                """
                INSERT INTO catalog_aliases (
                    id, exercise_id, alias, normalized_alias, alias_kind
                ) VALUES (?, ?, ?, ?, 'alias')
                """,
                (
                    f"{exercise_id}-alias-{index}",
                    exercise_id,
                    alias,
                    alias.casefold(),
                ),
            )


def test_search_is_ownership_safe_and_matches_sanitized_aliases(tmp_path):
    database = _database(tmp_path)
    repository = SQLiteExerciseCatalogRepository(database)
    _insert_exercise(
        database,
        exercise_id="public-squat",
        owner_user_id=None,
        name="Barbell squat",
        aliases=("深蹲", "squat"),
    )
    _insert_exercise(
        database,
        exercise_id="private-a",
        owner_user_id="user-a",
        name="My squat",
        aliases=("owner-only-movement",),
    )
    _insert_exercise(
        database,
        exercise_id="private-b",
        owner_user_id="user-b",
        name="Other squat",
        aliases=("foreign-movement",),
    )
    _insert_exercise(
        database,
        exercise_id="inactive",
        owner_user_id=None,
        name="Inactive squat",
        active=False,
    )

    assert {
        item.id for item in repository.search("user-a", "", limit=20)
    } == {"public-squat", "private-a"}
    assert [
        item.id
        for item in repository.search("user-a", '"owner-only")*', limit=20)
    ] == ["private-a"]
    assert repository.search("user-b", "owner-only-movement", limit=20) == ()


def test_search_ranks_recent_favorite_private_then_public(tmp_path):
    database = _database(tmp_path)
    repository = SQLiteExerciseCatalogRepository(database)
    for exercise_id, owner, name in (
        ("recent", None, "Recent"),
        ("favorite", None, "Favorite"),
        ("private", "user-a", "Private"),
        ("public-a", None, "Alpha"),
        ("public-z", None, "Zulu"),
    ):
        _insert_exercise(
            database,
            exercise_id=exercise_id,
            owner_user_id=owner,
            name=name,
        )

    repository.record_usage("user-a", "recent")
    repository.set_favorite("user-a", "favorite", True)

    results = repository.search("user-a", "", limit=20)

    assert [item.id for item in results] == [
        "recent",
        "favorite",
        "private",
        "public-a",
        "public-z",
    ]
    assert [item.rank_group for item in results] == [0, 1, 2, 3, 3]


def test_search_prioritizes_exact_canonical_and_alias_matches(tmp_path):
    database = _database(tmp_path)
    repository = SQLiteExerciseCatalogRepository(database)
    for exercise_id, name, aliases in (
        ("full", "杠铃深蹲", ("Barbell Full Squat",)),
        ("standard", "杠铃标准深蹲", ("Barbell Squat",)),
        ("olympic", "奥林匹克杠铃深蹲", ("Olympic Squat",)),
    ):
        _insert_exercise(
            database,
            exercise_id=exercise_id,
            owner_user_id=None,
            name=name,
            aliases=aliases,
        )

    assert repository.search("user-a", "杠铃深蹲", limit=20)[0].id == "full"
    assert (
        repository.search("user-a", "Barbell Full Squat", limit=20)[0].id
        == "full"
    )
    assert (
        repository.search("user-a", "杠铃标准深蹲", limit=20)[0].id
        == "standard"
    )
    assert (
        repository.search("user-a", "Barbell Squat", limit=20)[0].id
        == "standard"
    )


def test_search_exact_nfkc_alias_beats_recent_favorite_partial_before_limit(tmp_path):
    database = _database(tmp_path)
    repository = SQLiteExerciseCatalogRepository(database)
    _insert_exercise(
        database,
        exercise_id="exact-alias",
        owner_user_id=None,
        name="Standard squat",
        aliases=("ＢＡＲＢＥＬＬ ＳＱＵＡＴ",),
    )
    _insert_exercise(
        database,
        exercise_id="favorite-partial",
        owner_user_id=None,
        name="Favorite barbell squat variation",
    )
    repository.set_favorite("user-a", "favorite-partial", True)
    repository.record_usage("user-a", "favorite-partial")

    results = repository.search("user-a", "Barbell Squat", limit=1)

    assert [item.id for item in results] == ["exact-alias"]


def test_search_exact_nfkc_canonical_beats_recent_favorite_partial_before_limit(
    tmp_path,
):
    database = _database(tmp_path)
    repository = SQLiteExerciseCatalogRepository(database)
    _insert_exercise(
        database,
        exercise_id="exact-canonical",
        owner_user_id=None,
        name="ＢＡＲＢＥＬＬ ＳＱＵＡＴ",
    )
    _insert_exercise(
        database,
        exercise_id="favorite-partial",
        owner_user_id=None,
        name="Favorite barbell squat variation",
    )
    repository.set_favorite("user-a", "favorite-partial", True)
    repository.record_usage("user-a", "favorite-partial")

    results = repository.search("user-a", "Barbell Squat", limit=1)

    assert [item.id for item in results] == ["exact-canonical"]


def test_custom_exercise_is_owned_searchable_and_source_aware(tmp_path):
    repository = SQLiteExerciseCatalogRepository(
        _database(tmp_path),
        id_factory=iter(("custom", "alias-a", "usage")).__next__,
    )

    created = repository.create_custom_exercise(
        "user-a",
        NewCustomExercise(
            definition=ExerciseDefinition(
                name="My split squat",
                exercise_type="strength",
                primary_muscle="quadriceps",
                secondary_muscles=("glutes",),
                met=None,
                source="user_custom",
            ),
            aliases=("private-split-squat",),
        ),
    )

    assert created.id == "custom"
    assert created.owner_user_id == "user-a"
    assert created.secondary_muscles == ("glutes",)
    assert [
        item.id
        for item in repository.search("user-a", "private-split", limit=20)
    ] == ["custom"]
    assert repository.search("user-b", "private-split", limit=20) == ()


def test_favorite_and_usage_reject_foreign_or_inactive_exercises(tmp_path):
    database = _database(tmp_path)
    repository = SQLiteExerciseCatalogRepository(database)
    _insert_exercise(
        database,
        exercise_id="foreign",
        owner_user_id="user-b",
        name="Foreign",
    )
    _insert_exercise(
        database,
        exercise_id="inactive",
        owner_user_id=None,
        name="Inactive",
        active=False,
    )

    for exercise_id in ("foreign", "inactive"):
        for action in (
            lambda: repository.set_favorite("user-a", exercise_id, True),
            lambda: repository.record_usage("user-a", exercise_id),
        ):
            with pytest.raises(ExerciseCatalogRepositoryError) as raised:
                action()
            assert raised.value.code == "EXERCISE_NOT_VISIBLE"
