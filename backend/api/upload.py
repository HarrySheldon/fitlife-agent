from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile

from backend.api.dependencies import optional_current_user
from backend.api.utils import fail, ok
from backend.schemas import AuthenticatedUser
from backend.tools.data_access import data_path


router = APIRouter(prefix="/upload")


@router.post("/meals")
async def upload_meals(file: UploadFile, user: AuthenticatedUser | None = Depends(optional_current_user)):
    return await _save_csv_upload(file, data_path("meals.csv", _user_id(user)))


@router.post("/workouts")
async def upload_workouts(file: UploadFile, user: AuthenticatedUser | None = Depends(optional_current_user)):
    return await _save_csv_upload(file, data_path("workouts.csv", _user_id(user)))


async def _save_csv_upload(file: UploadFile, destination: Path):
    if not file.filename or not file.filename.endswith(".csv"):
        return fail("Only CSV files are supported", processing_mode="deterministic")
    content = await file.read()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return ok(
        {"filename": file.filename, "bytes": len(content)},
        "Upload saved",
        processing_mode="deterministic",
    )


def _user_id(user: AuthenticatedUser | None) -> str | None:
    return user.user_id if user else None
