from fastapi import APIRouter

from backend.api.utils import ok


router = APIRouter()


@router.get("/health")
def health():
    return ok({"status": "ok"})
