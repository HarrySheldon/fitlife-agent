from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from backend.api.dependencies import require_current_user
from backend.api.utils import ok
from backend.domain.errors import ApplicationError
from backend.i18n import message_for_request
from backend.schemas import AuthLoginRequest, AuthRegisterRequest, AuthSession, AuthenticatedUser
from backend.tools.auth_store import authenticate_user, create_access_token, register_user
from backend.tools.data_access import ensure_user_data


router = APIRouter(prefix="/auth")


@router.post("/register")
def register(request: Request, payload: AuthRegisterRequest):
    try:
        user = register_user(
            username=payload.username,
            email=payload.email,
            phone=payload.phone,
            password=payload.password,
            display_name=payload.display_name,
        )
    except ValueError as exc:
        raise ApplicationError(
            code="AUTH_IDENTIFIER_EXISTS",
            message="That account identifier is already registered.",
            status_code=400,
        ) from exc

    ensure_user_data(user.user_id)
    return ok(_session(user).model_dump(), message_for_request("AUTH_REGISTERED", request))


@router.post("/login")
def login(request: Request, payload: AuthLoginRequest):
    user = authenticate_user(payload.identifier, payload.password)
    if user is None:
        raise ApplicationError(
            code="AUTH_INVALID_CREDENTIALS",
            message="Invalid account or password.",
            status_code=401,
        )
    ensure_user_data(user.user_id)
    return ok(_session(user).model_dump(), message_for_request("AUTH_LOGGED_IN", request))


@router.get("/me")
def me(user: AuthenticatedUser = Depends(require_current_user)):
    return ok(user.model_dump())


def _session(user: AuthenticatedUser) -> AuthSession:
    return AuthSession(access_token=create_access_token(user), user=user)
