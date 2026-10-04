from fastapi import APIRouter, Request, Depends

from backend.api.utils import ok, request_id_for
from backend.api.dependencies import optional_current_user
from backend.evaluation import run_evaluation
from backend.schemas import EvalRunRequest, AuthenticatedUser


router = APIRouter(prefix="/eval")


@router.post("/run")
def run_eval(http_request: Request, request: EvalRunRequest | None = None,
             user: AuthenticatedUser | None = Depends(optional_current_user)):
    limit = request.limit if request else None
    return ok(run_evaluation(limit=limit, request_id=request_id_for(http_request),
                             user_id=user.user_id if user else None,
                             execution_mode=request.execution_mode if request else "live"), processing_mode="agent")
