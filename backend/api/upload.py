from pathlib import Path

from fastapi import APIRouter, UploadFile

from backend.api.utils import fail, ok
from backend.tools.data_access import data_path


router = APIRouter(prefix="/upload")


@router.post("/meals")
async def upload_meals(file: UploadFile):
    return await _save_csv_upload(file, data_path("meals.csv"))


@router.post("/workouts")
async def upload_workouts(file: UploadFile):
    return await _save_csv_upload(file, data_path("workouts.csv"))


async def _save_csv_upload(file: UploadFile, destination: Path):
    if not file.filename or not file.filename.endswith(".csv"):
        return fail("Only CSV files are supported")
    content = await file.read()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return ok({"filename": file.filename, "bytes": len(content)}, "Upload saved")
