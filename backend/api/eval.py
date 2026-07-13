from fastapi import APIRouter

from backend.api.utils import ok
from backend.evaluation import run_evaluation
from backend.schemas import EvalRunRequest


router = APIRouter(prefix="/eval")


@router.post("/run")
def run_eval(request: EvalRunRequest | None = None):
    limit = request.limit if request else None
    return ok(run_evaluation(limit=limit), processing_mode="agent")
