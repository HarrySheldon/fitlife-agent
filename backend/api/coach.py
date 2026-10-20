from fastapi import APIRouter, Depends, Request

from backend.agent.graph import run_contextual_coach_action
from backend.api.coach_conversations import coach_error, get_coach_admission_service
from backend.api.dependencies import optional_current_user
from backend.api.preference_context import preferences_for
from backend.api.utils import ok, request_id_for
from backend.application.use_cases.coach_turns import CoachTurnService
from backend.schemas import AuthenticatedUser, CoachActionRequest, CoachActionResponse


router = APIRouter(prefix="/coach")


@router.post("/action")
def coach_action(
    request: CoachActionRequest,
    http_request: Request,
    user: AuthenticatedUser | None = Depends(optional_current_user),
    admission: CoachTurnService = Depends(get_coach_admission_service),
):
    def produce() -> dict:
        return run_contextual_coach_action(
            surface=request.surface,
            action=request.action,
            date=request.date,
            question=request.question,
            user_id=user.user_id if user else None,
            preferences=preferences_for(user),
            request_id=request_id_for(http_request),
            language=request.language,
            answer_mode=request.answer_mode,
        )

    if user is None:
        # No account, no slot to take: the anonymous path was never able to run
        # two model calls for one owner, so admission would invent a constraint.
        result = produce()
    else:
        try:
            result = admission.run_legacy(
                user.user_id,
                question=request.question or request.action,
                action=request.action,
                surface=request.surface,
                produce=produce,
            )
        except Exception as error:
            raise coach_error(error) from None

    response = CoachActionResponse(
        surface=request.surface,
        action=request.action,
        answer_markdown=result["answer_markdown"],
        intent=result["intent"],
        trace=result["trace"],
        sources=result.get("sources", []),
        model=result["model"],
        request_id=result["request_id"],
        run_id=result["run_id"],
    )
    return ok(response.model_dump(), processing_mode="agent")
