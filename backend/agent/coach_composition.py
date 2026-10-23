"""Trusted assembly; user text can request a domain, never select an identity."""
import re
from backend.agent.context_builder import ExecutionPrincipal
from backend.agent.skills.catalog import SkillCatalog
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.handlers import BoundFitnessReads
from backend.agent.unified_coach import UnifiedCoachWorkflow
from backend.config import get_settings
from backend.domain.errors import configuration_error
from backend.infrastructure.auth.file_identity_repository import FileIdentityRepository
from backend.infrastructure.model_gateway.agent_decision_adapter import StructuredDecisionAdapter
from backend.rag.retriever import retrieve_knowledge
from backend.rag.vector_store import HashingEmbeddingProvider


def requested_domains(command):
    """Least-privilege grants for explicit topics, not a conversation allowlist.

    Unmatched requests may still be understood; they just cannot read records.
    Do not borrow permission from generated page text when raw user text exists.
    """
    text = command.raw_coach_question if command.raw_coach_question else command.question
    domains = {'profile'}
    if re.search(r'训练|訓練|健身|练胸|练腿|练背|练肩|器械|workout|exercise|training|chest|fitness', text, re.I):
        domains.add('training')
    if re.search(r'饮食|飲食|营养|營養|蛋白|热量|卡路里|diet|meal|nutrition|protein|calorie', text, re.I):
        domains.add('diet')
    # Mentioning a domain in an explicit exclusion does not request its records.
    for domain, words in [('diet', r'饮食|飲食|营养|diet|meals?|nutrition'),
                          ('training', r'训练|訓練|training|workouts?')]:
        exclusions = r'不要|不能|不允许|不允許|别|不需要|不授权|未授权|拒绝|禁止|无需|無需|do not|don.t|not consent|not authoriz|not permit|without permission|no access'
        if any(re.search(exclusions, clause, re.I) and re.search(words, clause, re.I)
               for clause in re.split(r'[，。；;.!?\n]', text)):
            domains.discard(domain)
    if command.trusted_page_intent and not command.raw_coach_question:
        if command.coach_action in {'explain_today', 'explain_weekly_report'}:
            domains.update({'training', 'diet'})
        elif command.coach_action == 'adjust_today_training':
            domains.add('training')
        elif command.coach_action in {'suggest_next_meal', 'suggest_targets'}:
            domains.add('diet')
    return frozenset(domains)


def local_knowledge(query, top_k, *, scope):
    allowed = {
        'training': {'fitness_rules.md', 'exercise_library.md', 'plan_rules.md'},
        'nutrition': {'nutrition_guidelines.md', 'meal_templates.md', 'plan_rules.md'},
    }.get(scope)
    results = retrieve_knowledge(query, top_k=5, provider=HashingEmbeddingProvider())
    return [item for item in results if allowed is None or item.get('source') in allowed][:top_k]


def build_unified_workflow(command, repository, gateway):
    if not callable(getattr(gateway, 'parse_structured', None)):
        raise configuration_error('Unified coach requires structured JSON generation')
    settings = get_settings()
    identities = FileIdentityRepository(settings.data_dir)
    principal = ExecutionPrincipal(command.user_id or '', authorized_domains=requested_domains(command))
    initial_token_version = identities.get_token_version(principal.owner_id)
    if initial_token_version is None:
        raise PermissionError('AUTHENTICATED_OWNER_REQUIRED')

    def authorize(actor):
        if (actor.owner_id != principal.owner_id
                or identities.get_token_version(actor.owner_id) != initial_token_version):
            raise PermissionError('ACCOUNT_ACCESS_REVOKED')
        if get_settings().coach_agent_mode != 'unified':
            raise PermissionError('AGENT_MODE_CHANGED')
        return principal.authorized_domains

    executor = ToolExecutor(principal=principal, reads=BoundFitnessReads(repository, principal.owner_id),
        catalog=SkillCatalog(), authorize=authorize, retriever=local_knowledge,
        language=command.language or 'en-US')
    return UnifiedCoachWorkflow(StructuredDecisionAdapter(gateway), executor,
        review_gateway=gateway, review_mode=settings.safety_review_mode)
