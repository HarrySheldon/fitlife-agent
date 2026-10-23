from backend.agent.tools.contracts import (
    SkillSearchArgs, ResourceReadArgs, QueryArgs, KnowledgeSearchArgs, CalculateArgs,
)

TOOL_MODELS = {
    'skills.search': SkillSearchArgs,
    'resources.read': ResourceReadArgs,
    'fitness.query': QueryArgs,
    'knowledge.search': KnowledgeSearchArgs,
    'fitness.calculate': CalculateArgs,
}


def tool_descriptions():
    return tuple({'name': name, 'parameters': model.model_json_schema(), 'read_only': True}
                 for name, model in sorted(TOOL_MODELS.items()))
