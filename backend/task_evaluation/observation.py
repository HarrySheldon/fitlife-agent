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
            if 'coach_messages' in tables:
                condition = ' WHERE user_id=?' if user_id is not None else ''
                parameters = (user_id,) if user_id is not None else ()
                result['coach_messages'] = connection.execute('SELECT COUNT(*) FROM coach_messages' + condition, parameters).fetchone()[0]
                result['coach_turns'] = connection.execute('SELECT COUNT(*) FROM coach_turns' + condition, parameters).fetchone()[0]
                prefix = condition + (' AND ' if condition else ' WHERE ')
                result['coach_unapproved_answers'] = connection.execute(
                    "SELECT COUNT(*) FROM coach_messages" + prefix + "role='coach' AND review_status!='approved'", parameters).fetchone()[0]
                result['coach_successes'] = connection.execute(
                    "SELECT COUNT(*) FROM coach_turns" + prefix + "status='succeeded'", parameters).fetchone()[0]
                result['coach_cancelled'] = connection.execute(
                    "SELECT COUNT(*) FROM coach_turns" + prefix + "status='cancelled'", parameters).fetchone()[0]
                result['coach_failed'] = connection.execute(
                    "SELECT COUNT(*) FROM coach_turns" + prefix + "status='failed'", parameters).fetchone()[0]
                result['coach_slot_holders'] = connection.execute(
                    "SELECT COUNT(*) FROM coach_turns" + prefix + "status IN ('queued','running')", parameters).fetchone()[0]
                from backend.domain.coach_answer import message_catalog
                result['coach_boundary_replies'] = 0
                result['coach_messages_with_sources'] = 0
                owner_clause = ' AND m.user_id=?' if user_id is not None else ''
                for body, receipt in connection.execute(
                    "SELECT m.body,t.receipt_json FROM coach_messages m JOIN coach_turns t ON m.turn_id=t.turn_id "
                    "AND m.user_id=t.user_id WHERE m.role='coach' AND m.review_status='approved'" + owner_clause, parameters):
                    try:
                        parsed = json.loads(receipt or '{}')
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(parsed, dict):
                        continue
                    context = parsed.get('context')
                    language = context.get('language') if isinstance(context, dict) else None
                    if language in {'zh-CN', 'en-US'} and body == message_catalog(language).out_of_scope:
                        result['coach_boundary_replies'] += 1
                    sources = parsed.get('sources')
                    if isinstance(sources, list) and sources:
                        result['coach_messages_with_sources'] += 1
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
