"""Read only final state, without copying record contents into reports."""
import sqlite3
import json
from pathlib import Path

# The two roots a plan patch may edit, in the order the product names them.
PLAN_DOMAINS = (("training", "workout_plan"), ("diet", "diet_plan"))
# Fields a candidate is forbidden to move. Comparing them is how a report can say
# "the target did not change" without quoting the plan.
PROTECTED_FIELDS = (
    ("diet_plan", "daily_calorie_target"),
    ("diet_plan", "daily_protein_target"),
    ("workout_plan", "weekly_training_days"),
    ("workout_plan", "rest_days"),
)


def observe_plan_tasks(connection, tables, user_id):
    """Bounded facts about this account's plan task, never its documents.

    The evidence a plan task produces is what persisted: how many rounds were
    claimed, how many candidates survived, which head was written, and whether the
    domain that already passed was left byte-identical. None of that needs the plan
    text, and a report that carried the text would be a second copy of the user's
    plan with a weaker retention rule than the one it came from.

    Task-scoped facts are only reported when the account has exactly one task. With
    zero or several, "the state of the task" is not a fact, and inventing one (the
    newest? the first?) is how a scenario passes for the wrong reason.
    """
    facts = {}
    if "plan_adjustment_sessions" not in tables:
        return facts
    tasks = connection.execute(
        "SELECT task_id, state, repair_rounds, base_plan_id, candidate_id "
        "FROM plan_adjustment_sessions WHERE user_id=? ORDER BY created_at, task_id",
        (user_id,)).fetchall()
    facts["plan_tasks"] = len(tasks)
    facts["plan_task_states"] = sorted(row[1] for row in tasks)
    if "plan_repair_rounds" in tables:
        facts["plan_rounds"] = connection.execute(
            "SELECT COUNT(*) FROM plan_repair_rounds r JOIN plan_adjustment_sessions s "
            "ON s.task_id = r.task_id WHERE s.user_id=?", (user_id,)).fetchone()[0]
        # Which rounds were claimed, in order. Two candidates and one index means
        # the second used the round the first had already reserved -- the fact a
        # reconnect has to preserve and a "claim a fresh round on retry" bug would
        # turn into ``[1, 2]``.
        facts["plan_round_indices"] = sorted(row[0] for row in connection.execute(
            "SELECT r.round_index FROM plan_repair_rounds r JOIN plan_adjustment_sessions s "
            "ON s.task_id = r.task_id WHERE s.user_id=?", (user_id,)))
    if "plan_candidate_submissions" in tables:
        facts["plan_candidates"] = connection.execute(
            "SELECT COUNT(*) FROM plan_candidate_submissions c JOIN plan_adjustment_sessions s "
            "ON s.task_id = c.task_id WHERE s.user_id=?", (user_id,)).fetchone()[0]
    if "plan_activation_receipts" in tables:
        facts["plan_activations"] = connection.execute(
            "SELECT COUNT(*) FROM plan_activation_receipts WHERE user_id=?",
            (user_id,)).fetchone()[0]
    if "plan_heads" in tables:
        row = connection.execute(
            "SELECT revision FROM plan_heads WHERE user_id=?", (user_id,)).fetchone()
        facts["plan_head_revision"] = 0 if row is None else row[0]
    if "plans" in tables:
        facts["plan_history"] = connection.execute(
            "SELECT COUNT(*) FROM plans WHERE user_id=?", (user_id,)).fetchone()[0]
    if len(tasks) == 1:
        facts.update(_task_facts(connection, tables, user_id, tasks[0]))
    return facts


def _task_facts(connection, tables, user_id, task):
    """The comparison facts a single task can answer about itself."""
    facts = {}
    documents = []
    if "plan_candidate_submissions" in tables:
        documents = [
            (row[0], json.loads(row[1]))
            for row in connection.execute(
                "SELECT round_index, candidate_json FROM plan_candidate_submissions "
                "WHERE task_id=? AND candidate_json IS NOT NULL ORDER BY round_index DESC LIMIT 2",
                (task[0],))
        ]
    if len(documents) == 2:
        # A deep comparison of the two most recent candidates, domain by domain.
        # This is the claim "the round that fixed diet did not rewrite training",
        # checked against the stored bytes instead of against the digest the same
        # code wrote.
        newer, older = documents[0][1], documents[1][1]
        facts["plan_domains_unchanged"] = sorted(
            domain for domain, root in PLAN_DOMAINS if newer.get(root) == older.get(root))
    if documents and "plans" in tables:
        row = connection.execute(
            "SELECT plan_json FROM plans WHERE user_id=? AND plan_id=?",
            (user_id, task[3])).fetchone()
        if row is not None:
            base = json.loads(row[0])
            candidate = documents[0][1]
            facts["plan_targets_unchanged"] = all(
                (base.get(root) or {}).get(field) == (candidate.get(root) or {}).get(field)
                for root, field in PROTECTED_FIELDS)
    return facts


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
                # Deliberately the file reader, not the plan repository factory:
                # this observes a directory an evaluation run seeded, so the file
                # layout *is* the subject. Routing it through the deployment's
                # configured store would measure the wrong thing.
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
            if user_id is not None:
                result.update(observe_plan_tasks(connection, tables, user_id))
            return result
        if actors is None:
            return observe()
        scoped = {actor: observe(user_id) for actor, user_id in actors.items()}
        return {**scoped.get("primary", {}), "actors": scoped,
                **{f"actor.{actor}.{key}": value for actor, facts in scoped.items() for key, value in facts.items() if isinstance(value, (bool, int))}}
    finally:
        connection.close()
