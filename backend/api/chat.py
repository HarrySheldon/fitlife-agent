from fastapi import APIRouter, Depends

from backend.agent.graph import run_fitlife_agent
from backend.api.dependencies import optional_current_user
from backend.api.preference_context import preferences_for
from backend.api.utils import ok
from backend.schemas import AuthenticatedUser, ChatRequest, ChatResponse


router = APIRouter()


@router.post("/chat")
def chat(request: ChatRequest, user: AuthenticatedUser | None = Depends(optional_current_user)):
    result = run_fitlife_agent(
        request.question,
        user.user_id if user else None,
        preferences=preferences_for(user),
    )
    response = ChatResponse(
        answer_markdown=result["answer_markdown"],
        intent=result["intent"],
        trace=result["trace"],
        sources=result["sources"],
        model=result["model"],
        request_id=result["request_id"],
    )
    return ok(response.model_dump(), processing_mode="agent")
