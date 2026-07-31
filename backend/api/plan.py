from fastapi import APIRouter, Depends

from backend.application.use_cases.generate_plan import GeneratePlan
from backend.api.dependencies import optional_current_user
from backend.api.utils import ok
from backend.infrastructure.repositories.cutover_fitness_repository import get_fitness_repository
from backend.schemas import AuthenticatedUser


router = APIRouter(prefix="/plan")


@router.post("/generate")
def generate_plan(user: AuthenticatedUser | None = Depends(optional_current_user)):
    plan = GeneratePlan(get_fitness_repository()).execute(user.user_id if user else None)
    return ok(plan, processing_mode="deterministic")
