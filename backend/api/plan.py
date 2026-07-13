from fastapi import APIRouter, Depends

from backend.application.use_cases.generate_plan import GeneratePlan
from backend.api.dependencies import optional_current_user
from backend.api.utils import ok
from backend.infrastructure.repositories.file_fitness_repository import FileFitnessRepository
from backend.schemas import AuthenticatedUser


router = APIRouter(prefix="/plan")


@router.post("/generate")
def generate_plan(user: AuthenticatedUser | None = Depends(optional_current_user)):
    plan = GeneratePlan(FileFitnessRepository()).execute(user.user_id if user else None)
    return ok(plan, processing_mode="deterministic")
