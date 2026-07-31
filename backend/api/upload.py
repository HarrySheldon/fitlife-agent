from fastapi import APIRouter, Depends, Request, UploadFile

from backend.api.dependencies import optional_current_user
from backend.api.utils import ok
from backend.domain.errors import invalid_upload_file_error
from backend.i18n import message_for_request
from backend.schemas import AuthenticatedUser
from backend.infrastructure.repositories.cutover_fitness_repository import get_fitness_repository
from backend.infrastructure.repositories.sqlite_fitness_repository import FitnessImportError
from backend.tools.data_access import write_data_bytes


router = APIRouter(prefix="/upload")


@router.post("/meals")
async def upload_meals(
    request: Request,
    file: UploadFile,
    user: AuthenticatedUser | None = Depends(optional_current_user),
):
    return await _save_csv_upload(
        file,
        "meals.csv",
        _user_id(user),
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
        "workouts.csv",
        _user_id(user),
        message_for_request("UPLOAD_SAVED", request, user),
    )


async def _save_csv_upload(
    file: UploadFile,
    filename: str,
    user_id: str | None,
    success_message: str,
):
    if not file.filename or not file.filename.endswith(".csv"):
        raise invalid_upload_file_error()
    content = await file.read()
    if user_id is not None:
        repository = get_fitness_repository()
        if repository.is_cutover(user_id):
            try:
                imported = (
                    repository.sqlite.import_meals_csv(user_id, content)
                    if filename == "meals.csv"
                    else repository.sqlite.import_workouts_csv(user_id, content)
                )
            except FitnessImportError:
                raise invalid_upload_file_error() from None
            return ok(
                {
                    "filename": file.filename,
                    "bytes": len(content),
                    "imported_count": imported.imported_count,
                    "replayed": imported.replayed,
                },
                success_message,
                processing_mode="deterministic",
            )
    write_data_bytes(filename, content, user_id)
    return ok(
        {"filename": file.filename, "bytes": len(content)},
        success_message,
        processing_mode="deterministic",
    )


def _user_id(user: AuthenticatedUser | None) -> str | None:
    return user.user_id if user else None
