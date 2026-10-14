"""Materialise synthetic declarations using authenticated public endpoints."""
from uuid import uuid4


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
        from backend.infrastructure.sqlite.database import SQLiteDatabase
        from backend.infrastructure.catalog.seed_foods import seed_food_payload
        from backend.infrastructure.catalog.seed_exercises import seed_exercise_payload
        database = SQLiteDatabase(root / "fitlife.sqlite3")
        for records, importer, field in ((initial.catalog.foods, seed_food_payload, "foods"), (initial.catalog.exercises, seed_exercise_payload, "exercises")):
            partitions = {}
            for record in records:
                partitions.setdefault((record.source_name, record.dataset_version), []).append(record.model_dump(mode="json"))
            for (source, version), rows in partitions.items():
                payload = {"schema_version": 1, "source_name": source, "dataset_version": version, "license": rows[0]["license"], "attribution": rows[0]["attribution"], field: rows}
                if field == "exercises":
                    payload["managed_sources"] = [source]
                importer(database, payload)
    for kind, records in (("meal", initial.records.meals), ("workout", initial.records.workouts)):
        for record in records:
            path = f"/api/v1/{kind}-drafts"
            draft = _request(client, "POST", path, headers, record.model_dump(mode="json"))
            confirmation = {**headers, "If-Match": str(draft["version"]), "Idempotency-Key": str(uuid4())}
            _request(client, "POST", path + "/" + draft["id"] + "/confirm", confirmation)
    for number in range(initial.plans.active_count + initial.plans.draft_count):
        draft = _request(client, "POST", "/plan/draft", headers)
        if number < initial.plans.active_count:
            _request(client, "POST", "/plan/activate", headers, {"draft_id": draft["draft_id"]})
    return actors
