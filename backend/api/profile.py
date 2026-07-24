from fastapi import APIRouter, Depends, Request

from backend.api.dependencies import optional_current_user, require_current_user
from backend.api.utils import ok
from backend.domain.errors import ApplicationError
from backend.i18n import message_for_request
from backend.schemas import (
    AuthenticatedUser,
    TrainingPersonalizationUpdateRequest,
    UserProfile,
)
from backend.tools.data_access import (
    read_profile,
    update_profile_atomically,
    write_profile,
)


router = APIRouter()


@router.get("/profile")
def get_profile(user: AuthenticatedUser | None = Depends(optional_current_user)):
    return ok(read_profile(_user_id(user)).model_dump(), processing_mode="deterministic")


@router.post("/profile")
def update_profile(request: Request, profile: UserProfile, user: AuthenticatedUser | None = Depends(optional_current_user)):
    if user is not None:
        raise ApplicationError(
            code="PROFILE_VERSIONED_WRITE_REQUIRED",
            message="Use the versioned profile or training personalization endpoint.",
            status_code=409,
            processing_mode="deterministic",
        )
    write_profile(profile)
    return ok(profile.model_dump(), message_for_request("PROFILE_SAVED", request, user), processing_mode="deterministic")


@router.patch("/profile/personalization")
def update_training_personalization(
    request: Request,
    payload: TrainingPersonalizationUpdateRequest,
    user: AuthenticatedUser = Depends(require_current_user),
):
    saved = update_profile_atomically(
        lambda current: current.model_copy(update=payload.model_dump()),
        user.user_id,
    )
    return ok(
        saved.model_dump(),
        message_for_request("PROFILE_SAVED", request, user),
        processing_mode="deterministic",
    )


def _user_id(user: AuthenticatedUser | None) -> str | None:
    return user.user_id if user else None
