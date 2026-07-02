from fastapi import APIRouter

from backend.api.utils import ok
from backend.schemas import UserProfile
from backend.tools.data_access import read_profile, write_profile


router = APIRouter()


@router.get("/profile")
def get_profile():
    return ok(read_profile().model_dump())


@router.post("/profile")
def update_profile(profile: UserProfile):
    write_profile(profile)
    return ok(profile.model_dump(), "Profile saved")
