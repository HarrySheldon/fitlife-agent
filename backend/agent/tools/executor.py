"""Every proposed action crosses this permission check, including cache hits."""
from copy import deepcopy
import json
from pydantic import ValidationError
from backend.agent.tools.registry import TOOL_MODELS
from backend.agent.tools.handlers import calculate, version_of
from backend.agent.skills.catalog import SkillResourceError


class ToolExecutor:
    def __init__(self, *, principal, reads, catalog, authorize, retriever, language='en-US'):
        self.principal, self.reads, self.catalog = principal, reads, catalog
        self.authorize, self.retriever, self.language = authorize, retriever, language
        self.observations = {}
        self.seen_ids = set()
        self.attempts = self.executions = self.denials = self.cache_hits = 0
        self._cache = {}

    def _domains(self):
        self.catalog.verify_release()
        current = self.authorize(self.principal)
        if not isinstance(current, frozenset):
            raise PermissionError('TRUSTED_DOMAIN_SNAPSHOT_REQUIRED')
        if self.reads.owner_id != self.principal.owner_id:
            raise PermissionError('OWNER_MISMATCH')
        if not self.principal.authorized_domains <= current:
            # The model has already seen the former scope. End access rather
            # than allowing a final answer to reuse revoked contextual data.
            raise PermissionError('SCOPE_ACCESS_REVOKED')
        return current & self.principal.authorized_domains

    def check_access(self):
        self._domains()

    def evidence(self, reference):
        domains = self._domains()
        result = self.observations.get(reference)
        if result is None or result['status'] != 'ok':
            raise PermissionError('EVIDENCE_NOT_AUTHORIZED')
        if not set(result.get('required_domains', ())) <= domains:
            raise PermissionError('EVIDENCE_NOT_AUTHORIZED')
        return deepcopy(result)

    async def execute(self, principal, call, context):
        context.raise_if_cancelled()
        self.attempts += 1
        try:
            if principal != self.principal:
                raise PermissionError('OWNER_MISMATCH')
            if call.call_id in self.seen_ids:
                raise ValueError('DUPLICATE_CALL_ID')
            self.seen_ids.add(call.call_id)
            model = TOOL_MODELS.get(call.tool)
            if model is None:
                raise PermissionError('TOOL_NOT_AUTHORIZED')
            args = model.model_validate(call.arguments)
            domains = self._domains()
            required = set()
            if call.tool == 'fitness.query':
                required.add(args.domain)
                if args.domain == 'profile':
                    from backend.agent.tools.handlers import PROFILE_FIELDS
                    required.update(PROFILE_FIELDS.get(field, 'invalid') for field in args.fields)
            if call.tool == 'fitness.calculate' and args.operation != 'validate_training':
                required.add('training' if args.operation == 'workout_analysis' else 'diet')
            if not required <= domains:
                raise PermissionError('SCOPE_PERMISSION_REQUIRED')

            # Only immutable release resources are cached. Mutable fitness records
            # are re-read, not guessed unchanged from a previous observation.
            key = (call.tool, json.dumps(call.arguments, sort_keys=True))
            cache_hit = call.tool == 'skills.search' and key in self._cache
            if cache_hit:
                self.cache_hits += 1
                data = deepcopy(self._cache[key])
            else:
                def handle():
                    # Authorization may change while the operation waits for a
                    # worker slot; validate again at the actual read boundary.
                    current_domains = self._domains()
                    if not required <= current_domains:
                        raise PermissionError('SCOPE_PERMISSION_REQUIRED')
                    self.executions += 1
                    if call.tool == 'skills.search':
                        return self.catalog.search(args.query, args.limit)
                    if call.tool == 'resources.read':
                        return self.catalog.read(args.resource_id)
                    if call.tool == 'fitness.query':
                        return self.reads.query(args, current_domains)
                    if call.tool == 'fitness.calculate':
                        return calculate(args, self.evidence, self.language)
                    # Use local knowledge only; never disclose health records in
                    # arbitrary remote embedding or search requests.
                    return self.retriever(args.query, args.top_k, scope=args.scope)
                data = await context.tool(call.tool, 'safe', handle)
                if call.tool == 'skills.search':
                    self._cache[key] = deepcopy(data)
            if len(json.dumps(data, ensure_ascii=False, default=str)) > 16000:
                raise ValueError('RESULT_TOO_LARGE')
            observation = {'call_id': call.call_id, 'tool': call.tool, 'status': 'ok',
                'data': data, 'evidence_id': call.call_id, 'source_version': version_of(data),
                'required_domains': sorted(required),
                'domain': getattr(args, 'domain', None), 'fields': getattr(args, 'fields', None)}
            self.observations[call.call_id] = deepcopy(observation)
            context.record('AGENT_TOOL_DECIDED', context, {'outcome': 'allow', 'cache_hits': int(cache_hit),
                'agent_tool': call.tool, 'tool_executions': self.executions, 'resource_release': self.catalog.release})
            return observation
        except (PermissionError, ValidationError, SkillResourceError, ValueError, KeyError) as error:
            if isinstance(error, SkillResourceError) and str(error) == 'RESOURCE_VERSION_CHANGED':
                raise
            self.denials += 1
            code = 'INVALID_TOOL_ARGUMENTS' if isinstance(error, (ValidationError, KeyError)) else str(error)
            if not code or len(code) > 80 or not code.replace('_', '').isalnum():
                code = 'TOOL_REJECTED'
            context.record('AGENT_TOOL_DECIDED', context, {'outcome': 'refuse', 'error_code': 'AGENT_TOOL_REJECTED',
                'agent_tool': call.tool if call.tool in TOOL_MODELS else 'other', 'tool_executions': self.executions})
            return {'call_id': call.call_id, 'tool': call.tool, 'status': 'denied', 'code': code}
