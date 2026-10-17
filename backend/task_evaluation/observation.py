"""Read only final state, without copying record contents into reports."""
import sqlite3
import json
from pathlib import Path


def observe_database(path, *, actors=None, data_dir=None):
    path = Path(path).resolve()
    if not path.exists():
        return {}
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        mappings = {"confirmed_meals": "meals", "confirmed_workouts": "training_sessions", "draft_count": "record_drafts", "idempotency_count": "idempotency_keys", "profile_version_count": "user_profile_versions"}
        def observe(user_id=None):
            result = {}
            for name, table in mappings.items():
                if table not in tables:
                    continue
                columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
                if user_id is not None and "user_id" not in columns:
                    continue
                condition = " WHERE user_id=?" if user_id is not None else ""
                parameters = (user_id,) if user_id is not None else ()
                result[name] = connection.execute(f'SELECT COUNT(*) FROM "{table}"{condition}', parameters).fetchone()[0]
                if table == "record_drafts":
                    result["draft_versions"] = [row[0] for row in connection.execute(f'SELECT version FROM record_drafts{condition} ORDER BY created_at,id', parameters)]
                    interactions = [json.loads(row[0]).get('interaction', {}) for row in connection.execute(
                        f'SELECT payload_json FROM record_drafts{condition} ORDER BY created_at,id', parameters)]
                    result['max_clarification_rounds'] = max((value.get('clarification_rounds', 0) for value in interactions), default=0)
                    result['question_group_count'] = sum(len(value.get('question_groups', [])) for value in interactions)
                    items = [item for value in interactions for item in value.get('items', [])]
                    result['item_states'] = [item['state'] for item in items]
                    result['item_revisions'] = [item['revision'] for item in items]
                    result['saved_item_count'] = sum(item['state'] == 'saved' for item in items)
            if 'entry_item_commits' in tables:
                condition = ' WHERE user_id=?' if user_id is not None else ''
                parameters = (user_id,) if user_id is not None else ()
                result['item_commit_count'] = connection.execute('SELECT COUNT(*) FROM entry_item_commits' + condition, parameters).fetchone()[0]
            if data_dir is not None and user_id is not None:
                user_root = Path(data_dir) / "users" / user_id
                history = len(list((user_root / "plans").glob("*.json")))
                result["active_plan_count"] = min(1, history)
                result["plan_draft_count"] = len(list((user_root / "plan-drafts").glob("*.json")))
                result["plan_history_count"] = history
                from backend.infrastructure.repositories.file_plan_repository import FilePlanRepository
                try:
                    plans = FilePlanRepository(data_dir).list(user_id)
                    result["plans_readable"] = len(plans) == history
                    result["plans_validated"] = all(plan.plan.validation.passed and not plan.plan.validation.violations for plan in plans)
                except Exception:
                    result["plans_readable"] = False
                    result["plans_validated"] = False
                runtime_path = Path(data_dir) / "agent_runtime.sqlite3"
                if runtime_path.exists():
                    with sqlite3.connect(runtime_path.resolve().as_uri() + "?mode=ro", uri=True) as runtime:
                        result["successful_runs"] = runtime.execute("SELECT COUNT(*) FROM agent_runs WHERE user_id=? AND status='succeeded'", (user_id,)).fetchone()[0]
            return result
        if actors is None:
            return observe()
        scoped = {actor: observe(user_id) for actor, user_id in actors.items()}
        return {**scoped.get("primary", {}), "actors": scoped,
                **{f"actor.{actor}.{key}": value for actor, facts in scoped.items() for key, value in facts.items() if isinstance(value, (bool, int))}}
    finally:
        connection.close()
