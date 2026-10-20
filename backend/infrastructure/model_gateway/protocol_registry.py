"""Explicit protocol registration; never silently fall back to another protocol."""
from backend.infrastructure.model_gateway.openai_chat_completions import OpenAIChatCompletionsAdapter
from backend.infrastructure.model_gateway.openai_responses import OpenAIResponsesAdapter


PROTOCOL_ADAPTERS = {
    "responses": OpenAIResponsesAdapter,
    "chat_completions": OpenAIChatCompletionsAdapter,
}


def adapter_for(protocol: str):
    try:
        return PROTOCOL_ADAPTERS[protocol]
    except KeyError:
        raise ValueError("Unsupported model protocol") from None
