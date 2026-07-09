from fastapi import APIRouter, Depends

from backend.api.dependencies import optional_current_user
from backend.api.utils import ok
from backend.schemas import AuthenticatedUser, UserProfile
from backend.tools.data_access import read_profile, write_profile


router = APIRouter()


@router.get("/profile")
def get_profile(user: AuthenticatedUser | None = Depends(optional_current_user)):
    return ok(read_profile(_user_id(user)).model_dump())


@router.post("/profile")
def update_profile(profile: UserProfile, user: AuthenticatedUser | None = Depends(optional_current_user)):
    write_profile(profile, _user_id(user))
    return ok(profile.model_dump(), "Profile saved")


def _user_id(user: AuthenticatedUser | None) -> str | None:
    return user.user_id if user else None
