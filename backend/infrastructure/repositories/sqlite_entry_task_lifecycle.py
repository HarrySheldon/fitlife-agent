"""Business-only task export and physical expiry. No model or gateway access."""
from datetime import datetime, timezone
import json

from backend.infrastructure.sqlite.database import SQLiteDatabase


_VALUES = ('name', 'amount', 'unit', 'calories', 'carbs', 'protein', 'fat',
           'basis_type', 'basis_amount', 'intake_ratio', 'selected_catalog_id',
           'duration_min', 'reps', 'set_count', 'load_kg', 'bodyweight',
           'primary_muscle', 'estimated_calories', 'is_estimate', 'met', 'device_calories')
_SOURCES = ('unknown', 'estimated', 'catalog', 'user_provided', 'measured')
_BUSINESS_SOURCES = ('public', 'user_custom', 'agent_estimate', 'legacy_import')
_ATTRIBUTION = ('catalog_id', 'source_name', 'source_record_id', 'dataset_version',
                'license', 'attribution', 'content_hash')


def _fields(value, names):
    return {key: value[key] for key in names if key in value.keys()}


def _values(values):
    projected = {key: value for key, value in values.items()
                 if key in _VALUES and (value is None or type(value) in (str, int, float, bool))}
    if values.get('source') in _BUSINESS_SOURCES:
        projected['source'] = values['source']
    if values.get('exercise_type') in ('strength', 'cardio'):
        projected['exercise_type'] = values['exercise_type']
    muscles = values.get('secondary_muscles')
    if isinstance(muscles, (list, tuple)) and all(isinstance(muscle, str) for muscle in muscles):
        projected['secondary_muscles'] = list(muscles)
    return projected


def _business(payload):
    result = _fields(payload, ('log_date', 'raw_text', 'parser_version'))
    result['candidates'] = []
    for item in payload.get('candidates', []):
        projected = _fields(item, ('id', 'kind', 'raw_text', 'normalized_text', 'subject_text',
                                   'meal_context', 'selected', 'selected_catalog_id'))
        projected['values'] = _values(item.get('values', {}))
        projected['assumptions'] = [text for text in item.get('assumptions', []) if isinstance(text, str)]
        provenance = item.get('provenance', {})
        projected['provenance'] = {key: value for key, value in provenance.items()
                                   if key in _ATTRIBUTION and isinstance(value, str)}
        source = provenance.get('source')
        if source in _BUSINESS_SOURCES:
            projected['provenance']['source'] = source
        result['candidates'].append(projected)
    interaction = payload.get('interaction')
    if isinstance(interaction, dict):
        progress = _fields(interaction, ('schema_version', 'clarification_rounds', 'active', 'status'))
        progress['items'] = []
        for item in interaction.get('items', []):
            projected = _fields(item, ('item_id', 'revision', 'state'))
            projected['values'] = _values(item.get('values', {}))
            projected['sources'] = {key: source for key, source in item.get('sources', {}).items()
                                    if key in (*_VALUES, 'source', 'exercise_type', 'secondary_muscles') and source in _SOURCES}
            projected['missing_fields'] = [key for key in item.get('missing_fields', []) if key in _VALUES]
            projected['assumptions'] = [text for text in item.get('assumptions', []) if isinstance(text, str)]
            progress['items'].append(projected)
        progress['question_groups'] = [
            {**_fields(group, ('group_id', 'asked_at', 'expected_version', 'answered')),
             'questions': [_fields(question, ('item_id', 'field', 'portion_options'))
                           for question in group.get('questions', []) if question.get('field') in _VALUES]}
            for group in interaction.get('question_groups', [])]
        result['interaction'] = progress
    return result


class SQLiteEntryTaskLifecycleRepository:
    def __init__(self, database: SQLiteDatabase, *, clock=None):
        self.database = database
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def expire_tasks(self, user_id: str, *, cutoff: datetime, dry_run: bool) -> tuple[str, ...]:
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError('An aware cutoff is required')
        cutoff = cutoff.astimezone(timezone.utc)
        if cutoff > self.clock():
            raise ValueError('Cutoff cannot be in the future')
        scope = self.database.connection if dry_run else self.database.transaction
        with scope() as connection:
            ids = []
            for row in connection.execute(
                "SELECT id, expires_at FROM record_drafts WHERE user_id=? AND kind='smart_entry' ORDER BY id", (user_id,)):
                expiry = datetime.fromisoformat(row['expires_at'].replace('Z', '+00:00'))
                if expiry.tzinfo is None or expiry.utcoffset() is None:
                    raise ValueError('Invalid stored expiry')
                if expiry.astimezone(timezone.utc) <= cutoff:
                    ids.append(row['id'])
            if not dry_run:
                for task_id in ids:
                    connection.execute("DELETE FROM record_drafts WHERE id=? AND user_id=? AND kind='smart_entry'", (task_id, user_id))
            return tuple(ids)

    def export_entry_tasks(self, user_id: str, *, max_bytes: int) -> bytes:
        output = bytearray()

        def append(value: bytes):
            if len(output) + len(value) > max_bytes:
                raise ValueError('Entry task export exceeds size limit')
            output.extend(value)

        with self.database.connection() as connection:
            # A read transaction keeps the sections coherent without a write lock.
            connection.execute('BEGIN')
            # Inspect lengths before materializing any potentially large body or ID.
            for query in (
                "SELECT COALESCE(SUM(length(CAST(payload_json AS BLOB))+length(CAST(id AS BLOB))),0) FROM record_drafts WHERE user_id=? AND kind='smart_entry'",
                'SELECT COALESCE(SUM(length(CAST(task_id AS BLOB))),0) FROM task_budgets WHERE user_id=?',
                'SELECT COALESCE(SUM(length(CAST(draft_id AS BLOB))+length(CAST(item_id AS BLOB))+length(CAST(meal_id AS BLOB))+length(CAST(meal_item_id AS BLOB))),0) FROM entry_item_commits WHERE user_id=?',
            ):
                if connection.execute(query, (user_id,)).fetchone()[0] > max_bytes:
                    raise ValueError('Entry task source exceeds size limit')
            append(b'{"drafts":[')
            first = True
            for row in connection.execute(
                "SELECT id,version,expires_at,created_at,updated_at,length(CAST(payload_json AS BLOB)) AS size FROM record_drafts WHERE user_id=? AND kind='smart_entry' ORDER BY id", (user_id,)):
                if row['size'] > max_bytes:
                    raise ValueError('Entry task body exceeds size limit')
                item = _fields(row, ('id', 'version', 'expires_at', 'created_at', 'updated_at'))
                body = connection.execute('SELECT payload_json FROM record_drafts WHERE id=? AND user_id=?', (row['id'], user_id)).fetchone()[0]
                item['payload'] = _business(json.loads(body))
                append((b'' if first else b',') + json.dumps(item, ensure_ascii=False, allow_nan=False).encode('utf-8'))
                first = False
            for section, query in (
                ('budgets', '''SELECT b.task_id,b.call_limit,b.token_limit,
                    COALESCE(SUM(CASE WHEN o.usage_known IS NULL THEN 0 WHEN o.usage_known=1 THEN o.actual_calls ELSE o.calls END),0) AS spent_calls,
                    COALESCE(SUM(CASE WHEN o.usage_known IS NULL THEN 0 WHEN o.usage_known=1 THEN o.actual_tokens ELSE o.tokens END),0) AS spent_tokens,
                    COALESCE(SUM(CASE WHEN o.usage_known IS NULL THEN o.calls ELSE 0 END),0) AS reserved_calls,
                    COALESCE(SUM(CASE WHEN o.usage_known IS NULL THEN o.tokens ELSE 0 END),0) AS reserved_tokens
                    FROM task_budgets b LEFT JOIN task_budget_operations o ON b.user_id=o.user_id AND b.task_id=o.task_id
                    WHERE b.user_id=? GROUP BY b.task_id,b.call_limit,b.token_limit ORDER BY b.task_id'''),
                ('commits', 'SELECT draft_id,item_id,item_revision,meal_id,meal_item_id,created_at FROM entry_item_commits WHERE user_id=? ORDER BY draft_id,item_id,item_revision'),
            ):
                append(b'],"' + section.encode() + b'":[')
                first = True
                for row in connection.execute(query, (user_id,)):
                    append((b'' if first else b',') + json.dumps(dict(row), ensure_ascii=False, allow_nan=False).encode('utf-8'))
                    first = False
            append(b']}\n')
        return bytes(output)
