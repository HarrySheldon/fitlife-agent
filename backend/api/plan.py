from fastapi import APIRouter, Depends

from backend.api.dependencies import optional_current_user
from backend.api.utils import ok
from backend.schemas import AuthenticatedUser
from backend.tools.data_access import read_profile
from backend.tools.report_generator import generate_next_week_plan


router = APIRouter(prefix="/plan")


@router.post("/generate")
def generate_plan(user: AuthenticatedUser | None = Depends(optional_current_user)):
    profile = read_profile(user.user_id if user else None)
    plan = generate_next_week_plan(profile.model_dump())
    plan["trace"] = {"tool_calls": ["load_profile", "generate_next_week_plan", "validate_plan"]}
    return ok(plan)
