"""Materialise synthetic declarations using authenticated public endpoints."""
from datetime import datetime, timezone
from uuid import uuid4

# One fixed instant for seeded plan activations. A wall-clock value would make the
# legacy head ordering depend on when the run happened, and a plan scenario pins
# the revision it expects a confirmation to advance.
SEEDED_ACTIVATION = datetime(2026, 1, 1, tzinfo=timezone.utc)


class UnsupportedSeed(Exception):
    pass


class ActorHeaders(dict):
    def __init__(self):
        super().__init__()
        self.user_ids = {}


def _request(client, method, path, headers=None, body=None):
    response = client.request(method, path, headers=headers, json=body)
    if response.status_code != 200:
        raise UnsupportedSeed("Seed rejected")
    return response.json()["data"]


def _database(root):
    from backend.infrastructure.sqlite.database import SQLiteDatabase
    return SQLiteDatabase(root / "fitlife.sqlite3")


def seed_plan_constraints(root, user_id, seed):
    """The versioned rows a plan task's hard constraints come from.

    The setup form writes exactly these four things -- a profile version, a goal
    version, a confirmed target version and an allergy version -- so the seed goes
    through the same repository rather than through four endpoints whose preview
    tokens would make the setup form the subject of the test.
    """
    from backend.application.ports.profile_target_repository import (
        GoalVersionInput,
        ProfileVersionInput,
        TargetVersionInput,
    )
    from backend.infrastructure.repositories.sqlite_profile_target_repository import (
        SQLiteProfileTargetRepository,
    )

    profiles = SQLiteProfileTargetRepository(_database(root))
    effective = seed.effective_from.isoformat()
    setup = profiles.bootstrap(
        user_id,
        ProfileVersionInput(
            age=seed.age, height_cm=seed.height_cm, weight_kg=seed.weight_kg,
            energy_parameter=seed.energy_parameter, activity_level=seed.activity_level,
            auto_target_disabled=False,
            safety_conditions=tuple(seed.safety_conditions),
            effective_from=effective,
        ),
        GoalVersionInput(goal=seed.goal, effective_from=effective),
    )
    profiles.append_target(user_id, TargetVersionInput(
        profile_version_id=setup.profile.id,
        overall_goal_version_id=setup.goal.id,
        calories=seed.calories, carbs=seed.carbs, protein=seed.protein, fat=seed.fat,
        source="manual", formula_version=None,
        rationale={"confirmed_warnings": []}, effective_from=effective))
    seed_plan_safety(root, user_id, seed)


def seed_plan_safety(root, user_id, seed):
    """The allergy version a plan task is frozen against.

    Separate from the rest of the seed because it has to be written *last*. The
    legacy import that makes SQLite the plan store also migrates each account's
    allergy list out of ``user_profile.json``, and a freshly registered account's
    file says ``[]``. Run in the other order the migration's empty list becomes the
    newest version, so the task is frozen against "verified to have no
    restrictions" and the diet rule can never fire -- a suite that then cannot
    detect a diet defect at all. Re-applying the declared list after the import
    makes the scenario's own value the one the task is frozen with.
    """
    from backend.application.ports.profile_target_repository import SafetyVersionInput
    from backend.infrastructure.repositories.sqlite_profile_target_repository import (
        SQLiteProfileTargetRepository,
    )

    SQLiteProfileTargetRepository(_database(root)).append_safety_if_changed(
        user_id,
        SafetyVersionInput(allergies_or_restrictions=tuple(seed.allergies_or_restrictions)))


def seed_declared_plan(root, user_id, seed):
    """Write the plan a scenario declared, before the store is migrated.

    It lands as a file because that is what this deployment's data directory holds
    at this point; ``activate_sqlite_plan_store`` then imports it, so the scenario
    measures the same migration path an operator would run.
    """
    from backend.application.ports.plan_repository import StoredPlan
    from backend.infrastructure.repositories.file_plan_repository import FilePlanRepository
    from backend.schemas import GeneratedPlan

    FilePlanRepository(root).save(user_id, StoredPlan(
        plan_id=seed.plan_id,
        activated_at=seed.activated_at or SEEDED_ACTIVATION,
        kind="deterministic",
        plan=GeneratedPlan.model_validate(seed.document)))


def activate_sqlite_plan_store(settings, root):
    """Import the seeded directory into SQLite, then make SQLite authoritative.

    Only a store that can compare-and-swap a head can confirm a candidate, so a
    plan scenario that never confirms anything is the only kind that could run on
    the file store. Doing the migration here -- with the same import function an
    operator runs -- is what makes the confirmation evidence real instead of a
    claim about a deployment nobody configured.
    """
    from backend.infrastructure.sqlite.import_legacy_plans import apply

    apply(root, _database(root))
    settings.plan_storage_mode = "sqlite"


def seed_environment(client, scenario, root):
    initial = scenario.initial_state
    actors = ActorHeaders()
    for actor in ["primary", *initial.authorization.additional_users]:
        registration = _request(client, "POST", "/auth/register", body={"username": "eval-" + actor, "password": "synthetic-password123", "display_name": "Synthetic"})
        actors[actor] = {"Authorization": "Bearer " + registration["access_token"]}
        actors.user_ids[actor] = registration["user"]["user_id"]
    headers = actors["primary"]
    if initial.profile:
        profile = initial.profile.model_dump(mode="json", exclude_none=True, exclude_unset=True)
        legacy = {"gender", "goal", "weekly_training_frequency", "diet_preferences", "allergies_or_restrictions", "target_weight_kg", "daily_calorie_target", "daily_protein_target"}
        if any(key in profile for key in legacy):
            raise UnsupportedSeed("Legacy profile seed")
        body = {key: value for key, value in profile.items() if key not in legacy}
        body.setdefault("effective_from", "2026-01-01T00:00:00Z")
        body.setdefault("energy_parameter", "neutral")
        body.setdefault("activity_level", "moderate")
        _request(client, "PUT", "/api/v1/profile", headers, body)
    if initial.catalog:
        from backend.infrastructure.catalog.seed_foods import seed_food_payload
        from backend.infrastructure.catalog.seed_exercises import seed_exercise_payload
        database = _database(root)
        for records, importer, field in ((initial.catalog.foods, seed_food_payload, "foods"), (initial.catalog.exercises, seed_exercise_payload, "exercises")):
            partitions = {}
            for record in records:
                partitions.setdefault((record.source_name, record.dataset_version), []).append(record.model_dump(mode="json"))
            for (source, version), rows in partitions.items():
                payload = {"schema_version": 1, "source_name": source, "dataset_version": version, "license": rows[0]["license"], "attribution": rows[0]["attribution"], field: rows}
                if field == "exercises":
                    payload["managed_sources"] = [source]
                importer(database, payload)
    if initial.plan_constraints:
        seed_plan_constraints(root, actors.user_ids["primary"], initial.plan_constraints)
    for kind, records in (("meal", initial.records.meals), ("workout", initial.records.workouts)):
        for record in records:
            path = f"/api/v1/{kind}-drafts"
            draft = _request(client, "POST", path, headers, record.model_dump(mode="json"))
            confirmation = {**headers, "If-Match": str(draft["version"]), "Idempotency-Key": str(uuid4())}
            _request(client, "POST", path + "/" + draft["id"] + "/confirm", confirmation)
    if initial.plans.document is not None:
        seed_declared_plan(root, actors.user_ids["primary"], initial.plans)
    for number in range(initial.plans.active_count + initial.plans.draft_count):
        draft = _request(client, "POST", "/plan/draft", headers)
        if number < initial.plans.active_count:
            _request(client, "POST", "/plan/activate", headers, {"draft_id": draft["draft_id"]})
    return actors
