from fastapi import APIRouter, Depends, Request

from backend.api.dependencies import optional_current_user
from backend.api.utils import ok
from backend.i18n import message_for_request
from backend.schemas import AuthenticatedUser, UserProfile
from backend.tools.data_access import read_profile, write_profile


router = APIRouter()


@router.get("/profile")
def get_profile(user: AuthenticatedUser | None = Depends(optional_current_user)):
    return ok(read_profile(_user_id(user)).model_dump(), processing_mode="deterministic")


@router.post("/profile")
def update_profile(request: Request, profile: UserProfile, user: AuthenticatedUser | None = Depends(optional_current_user)):
    write_profile(profile, _user_id(user))
    return ok(profile.model_dump(), message_for_request("PROFILE_SAVED", request, user), processing_mode="deterministic")


def _user_id(user: AuthenticatedUser | None) -> str | None:
    return user.user_id if user else None
