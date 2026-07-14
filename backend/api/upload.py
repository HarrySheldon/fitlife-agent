from pathlib import Path

from fastapi import APIRouter, Depends, Request, UploadFile

from backend.api.dependencies import optional_current_user
from backend.api.utils import ok
from backend.domain.errors import invalid_upload_file_error
from backend.i18n import message_for_request
from backend.schemas import AuthenticatedUser
from backend.tools.data_access import data_path


router = APIRouter(prefix="/upload")


@router.post("/meals")
async def upload_meals(
    request: Request,
    file: UploadFile,
    user: AuthenticatedUser | None = Depends(optional_current_user),
):
    return await _save_csv_upload(
        file,
        data_path("meals.csv", _user_id(user)),
        message_for_request("UPLOAD_SAVED", request, user),
    )


@router.post("/workouts")
async def upload_workouts(
    request: Request,
    file: UploadFile,
    user: AuthenticatedUser | None = Depends(optional_current_user),
):
    return await _save_csv_upload(
        file,
        data_path("workouts.csv", _user_id(user)),
        message_for_request("UPLOAD_SAVED", request, user),
    )


async def _save_csv_upload(file: UploadFile, destination: Path, success_message: str):
    if not file.filename or not file.filename.endswith(".csv"):
        raise invalid_upload_file_error()
    content = await file.read()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return ok(
        {"filename": file.filename, "bytes": len(content)},
        success_message,
        processing_mode="deterministic",
    )


def _user_id(user: AuthenticatedUser | None) -> str | None:
    return user.user_id if user else None
