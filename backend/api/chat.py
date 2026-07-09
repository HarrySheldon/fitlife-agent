from fastapi import APIRouter, Depends

from backend.agent.graph import run_fitlife_agent
from backend.api.dependencies import optional_current_user
from backend.api.utils import ok
from backend.schemas import AuthenticatedUser, ChatRequest


router = APIRouter()


@router.post("/chat")
def chat(request: ChatRequest, user: AuthenticatedUser | None = Depends(optional_current_user)):
    result = run_fitlife_agent(request.question, user.user_id if user else None)
    return ok(
        {
            "answer_markdown": result["answer_markdown"],
            "intent": result["intent"],
            "trace": result["trace"],
            "sources": result["sources"],
        }
    )
