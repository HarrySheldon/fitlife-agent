from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.dependencies import require_current_user
from backend.api.utils import ok
from backend.schemas import AuthLoginRequest, AuthRegisterRequest, AuthSession, AuthenticatedUser
from backend.tools.auth_store import authenticate_user, create_access_token, register_user
from backend.tools.data_access import ensure_user_data


router = APIRouter(prefix="/auth")


@router.post("/register")
def register(request: AuthRegisterRequest):
    try:
        user = register_user(
            username=request.username,
            email=request.email,
            phone=request.phone,
            password=request.password,
            display_name=request.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    ensure_user_data(user.user_id)
    return ok(_session(user).model_dump(), "Registered")


@router.post("/login")
def login(request: AuthLoginRequest):
    user = authenticate_user(request.identifier, request.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid account or password")
    ensure_user_data(user.user_id)
    return ok(_session(user).model_dump(), "Logged in")


@router.get("/me")
def me(user: AuthenticatedUser = Depends(require_current_user)):
    return ok(user.model_dump())


def _session(user: AuthenticatedUser) -> AuthSession:
    return AuthSession(access_token=create_access_token(user), user=user)
