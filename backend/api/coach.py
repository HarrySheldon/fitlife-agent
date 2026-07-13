from fastapi import APIRouter, Depends

from backend.agent.graph import run_contextual_coach_action
from backend.api.dependencies import optional_current_user
from backend.api.utils import ok
from backend.schemas import AuthenticatedUser, CoachActionRequest, CoachActionResponse


router = APIRouter(prefix="/coach")


@router.post("/action")
def coach_action(
    request: CoachActionRequest,
    user: AuthenticatedUser | None = Depends(optional_current_user),
):
    result = run_contextual_coach_action(
        surface=request.surface,
        action=request.action,
        date=request.date,
        question=request.question,
        user_id=user.user_id if user else None,
    )
    response = CoachActionResponse(
        surface=request.surface,
        action=request.action,
        answer_markdown=result["answer_markdown"],
        intent=result["intent"],
        trace=result["trace"],
        sources=result.get("sources", []),
        model=result["model"],
        request_id=result["request_id"],
    )
    return ok(response.model_dump(), processing_mode="agent")
