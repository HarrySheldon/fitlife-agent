from fastapi import APIRouter, Depends
from backend.agent.graph import DEFAULT_AGENT_RUNTIME
from backend.api.dependencies import optional_current_user
from backend.api.utils import ok
from backend.domain.errors import ApplicationError
from backend.schemas import AuthenticatedUser

router = APIRouter(prefix="/agent/runs")

def _user_id(user): return user.user_id if user else None
def _not_found(run_id): return ApplicationError(code="RUN_NOT_FOUND", message="The Agent run was not found.", status_code=404, run_id=run_id)

@router.get("/{run_id}")
async def get_run(run_id: str, user: AuthenticatedUser | None = Depends(optional_current_user)):
    try: snapshot = await DEFAULT_AGENT_RUNTIME.get_status(run_id, _user_id(user))
    except KeyError: raise _not_found(run_id) from None
    return ok(snapshot.__dict__, processing_mode="agent")

@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str, user: AuthenticatedUser | None = Depends(optional_current_user)):
    result = await DEFAULT_AGENT_RUNTIME.cancel(run_id, _user_id(user))
    if result.status == "not_found": raise _not_found(run_id)
    return ok(result.__dict__, processing_mode="agent")
