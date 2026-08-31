from fastapi import APIRouter, Request

from backend.api.utils import ok, request_id_for
from backend.evaluation import run_evaluation
from backend.schemas import EvalRunRequest


router = APIRouter(prefix="/eval")


@router.post("/run")
def run_eval(http_request: Request, request: EvalRunRequest | None = None):
    limit = request.limit if request else None
    return ok(run_evaluation(limit=limit, request_id=request_id_for(http_request)), processing_mode="agent")
