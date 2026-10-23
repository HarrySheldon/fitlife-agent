"""Stable instructions and bounded, explicitly sourced dynamic context."""
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import re
from backend.application.ports.agent_decision_gateway import AgentDecisionRequest
from backend.domain.coach_answer import resolve_language

SYSTEM_INSTRUCTIONS = (Path(__file__).parent / 'prompts' / 'coach_system.md').read_text(encoding='utf-8')


@dataclass(frozen=True)
class ExecutionPrincipal:
    owner_id: str
    conversation_id: str = ''
    authorized_domains: frozenset[str] = frozenset()
    policy_version: str = 'u1'

    def __post_init__(self):
        if not isinstance(self.owner_id, str) or not self.owner_id.strip():
            raise PermissionError('AUTHENTICATED_OWNER_REQUIRED')
        if not isinstance(self.authorized_domains, frozenset):
            raise PermissionError('TRUSTED_DOMAIN_SNAPSHOT_REQUIRED')
        if not self.authorized_domains <= {'profile', 'training', 'diet'}:
            raise PermissionError('UNKNOWN_DOMAIN')


def serialized(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def redact(text):
    return re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[redacted]', text)


def build_context(principal, command, tool_descriptions, *, now=None, max_chars=24000):
    now = now or datetime.now(timezone.utc)
    messages = []
    for item in command.recent_history[-12:]:
        if item.get('conversation_id', principal.conversation_id) != principal.conversation_id:
            continue
        if item.get('created_at'):
            try:
                stamp = datetime.fromisoformat(item['created_at'].replace('Z', '+00:00'))
                if stamp.tzinfo is None or stamp < now - timedelta(days=90):
                    continue
            except (ValueError, TypeError):
                continue
        if item.get('role') in {'user', 'assistant'} and isinstance(item.get('body'), str):
            messages.append({'role': item['role'], 'content': redact(item['body'][:2000]),
                             'source': 'untrusted_history'})
    messages.append({'role': 'user', 'content': redact(command.question), 'source': 'current_request'})
    messages.append({'role': 'user', 'source': 'runtime_state', 'content': serialized({
        'revision': 0, 'as_of': now.isoformat(), 'language': resolve_language(requested=command.language),
        'answer_mode': command.answer_mode or 'brief', 'phase': 'understand',
        'coach_action': command.coach_action,
    })})
    while len(serialized(messages)) > max_chars and len(messages) > 2:
        messages.pop(0)
    if len(serialized(messages)) > max_chars:
        raise ValueError('CONTEXT_BUDGET_EXCEEDED')
    return AgentDecisionRequest(SYSTEM_INSTRUCTIONS, tuple(messages),
                                tuple(sorted(tool_descriptions, key=lambda item: item['name'])))
