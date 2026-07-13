"""Compatibility imports for the model gateway infrastructure adapter."""

from backend.infrastructure.model_gateway.openai_responses import (
    OpenAIResponsesAdapter,
    build_model_gateway,
)

build_llm_adapter = build_model_gateway

__all__ = ["OpenAIResponsesAdapter", "build_llm_adapter", "build_model_gateway"]
