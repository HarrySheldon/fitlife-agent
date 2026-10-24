"""Every proposed action crosses this permission check, including cache hits."""
from copy import deepcopy
import json
from pydantic import ValidationError
from backend.agent.tools.registry import RECORDED_TOOL_NAMES, SPECS
from backend.agent.tools.handlers import version_of
from backend.agent.tools.spec import ToolAccess, ToolContext, ToolSpec
from backend.agent.skills.catalog import SkillResourceError


class ToolExecutor:
    def __init__(self, *, principal, reads, catalog, authorize, retriever, language='en-US',
                 specs=None, session=None):
        self.principal, self.reads, self.catalog = principal, reads, catalog
        self.authorize, self.retriever, self.language = authorize, retriever, language
        self.specs: dict[str, ToolSpec] = dict(SPECS if specs is None else specs)
        self.session = session
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

    def _access(self, spec, args, domains):
        return ToolAccess(principal=self.principal, args=args, domains=domains,
                          required=frozenset(spec.required_domains(args)), session=self.session)

    def _context(self, domains):
        return ToolContext(catalog=self.catalog, reads=self.reads, retriever=self.retriever,
                           language=self.language, evidence=self.evidence, domains=domains,
                           session=self.session)

    async def execute(self, principal, call, context):
        context.raise_if_cancelled()
        self.attempts += 1
        try:
            if principal != self.principal:
                raise PermissionError('OWNER_MISMATCH')
            if call.call_id in self.seen_ids:
                raise ValueError('DUPLICATE_CALL_ID')
            self.seen_ids.add(call.call_id)
            spec = self.specs.get(call.tool)
            if spec is None:
                raise PermissionError('TOOL_NOT_AUTHORIZED')
            args = spec.args_model.model_validate(call.arguments)
            domains = self._domains()
            access = self._access(spec, args, domains)
            spec.authorize(access)
            required = access.required

            # Only immutable release resources are cached. Mutable fitness records
            # are re-read, not guessed unchanged from a previous observation.
            key = (call.tool, json.dumps(call.arguments, sort_keys=True))
            cache_hit = spec.cacheable and key in self._cache
            if cache_hit:
                self.cache_hits += 1
                data = deepcopy(self._cache[key])
            else:
                def handle():
                    # Authorization may change while the operation waits for a
                    # worker slot; validate again at the actual read boundary.
                    current = self._domains()
                    current_access = self._access(spec, args, current)
                    spec.authorize(current_access)
                    self.executions += 1
                    return spec.handler(args, self._context(current))
                # A draft write is never replayed: the runtime must not turn one
                # submitted candidate into two writes. Business idempotency is
                # the task's operation id, not a transport retry.
                data = await context.tool(call.tool, spec.replay, handle)
                if spec.cacheable:
                    self._cache[key] = deepcopy(data)
            if len(json.dumps(data, ensure_ascii=False, default=str)) > spec.max_result_chars:
                raise ValueError('RESULT_TOO_LARGE')
            observation = {'call_id': call.call_id, 'tool': call.tool, 'status': 'ok',
                'data': data, 'evidence_id': call.call_id, 'source_version': version_of(data),
                'required_domains': sorted(required), 'public': spec.public,
                'domain': getattr(args, 'domain', None), 'fields': getattr(args, 'fields', None)}
            self.observations[call.call_id] = deepcopy(observation)
            context.record('AGENT_TOOL_DECIDED', context, {'outcome': 'allow', 'cache_hits': int(cache_hit),
                'agent_tool': call.tool if call.tool in RECORDED_TOOL_NAMES else 'other',
                'tool_executions': self.executions, 'resource_release': self.catalog.release})
            return observation
        except (PermissionError, ValidationError, SkillResourceError, ValueError, KeyError) as error:
            if isinstance(error, SkillResourceError) and str(error) == 'RESOURCE_VERSION_CHANGED':
                raise
            self.denials += 1
            code = 'INVALID_TOOL_ARGUMENTS' if isinstance(error, (ValidationError, KeyError)) else str(error)
            if not code or len(code) > 80 or not code.replace('_', '').isalnum():
                code = 'TOOL_REJECTED'
            context.record('AGENT_TOOL_DECIDED', context, {'outcome': 'refuse', 'error_code': 'AGENT_TOOL_REJECTED',
                'agent_tool': call.tool if call.tool in RECORDED_TOOL_NAMES else 'other',
                'tool_executions': self.executions})
            return {'call_id': call.call_id, 'tool': call.tool, 'status': 'denied', 'code': code}
