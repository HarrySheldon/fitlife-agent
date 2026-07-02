from fastapi import APIRouter

from backend.api.utils import ok
from backend.tools.data_access import read_profile
from backend.tools.report_generator import generate_next_week_plan


router = APIRouter(prefix="/plan")


@router.post("/generate")
def generate_plan():
    profile = read_profile()
    plan = generate_next_week_plan(profile.model_dump())
    plan["trace"] = {"tool_calls": ["load_profile", "generate_next_week_plan", "validate_plan"]}
    return ok(plan)
