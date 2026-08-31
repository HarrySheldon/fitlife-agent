from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.api import account, agent_runs, auth, calendar, chat, coach, dashboard, eval, exercise_catalog, food_catalog, health, meals, plan, profile, profile_targets, report, settings as settings_api, smart_entry, today, upload, workouts
from backend.api.utils import application_error_response
from backend.config import get_settings
from backend.domain.errors import ApplicationError
from backend.domain.user_preferences import AppLanguage
from backend.i18n import (
    language_for_request,
    language_from_accept_language,
    translate_public_message,
)
from backend.infrastructure.startup import run_startup
from backend.schemas import ApiError, ApiResponse
from backend.agent.runtime import BudgetExceeded, RunCancelled, RunTimedOut, RuntimeControlError


def _safe_language_for_request(request: Request) -> AppLanguage:
    try:
        return language_for_request(request)
    except Exception:
        return language_from_accept_language(request.headers.get("accept-language"))


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    run_startup()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="FitLife Agent API", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def assign_request_id(request: Request, call_next):
        request.state.request_id = uuid4().hex
        response = await call_next(request)
        response.headers["x-request-id"] = request.state.request_id
        return response

    @app.exception_handler(ApplicationError)
    async def handle_application_error(request: Request, error: ApplicationError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content=application_error_response(error, _safe_language_for_request(request), request.state.request_id),
            headers={"x-request-id": request.state.request_id},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, _error: RequestValidationError) -> JSONResponse:
        message = translate_public_message(
            "VALIDATION_ERROR", _safe_language_for_request(request)
        )
        response = ApiResponse(
            success=False,
            data=None,
            message=message,
            error=ApiError(code="VALIDATION_ERROR", message=message, action="Check the request fields and try again.", request_id=request.state.request_id),
        )
        return JSONResponse(status_code=422, content=response.model_dump(exclude={"processing_mode"}), headers={"x-request-id": request.state.request_id})

    @app.exception_handler(RuntimeControlError)
    async def handle_runtime_control_error(request: Request, error: RuntimeControlError) -> JSONResponse:
        status_code, action, retryable = {
            BudgetExceeded: (429, "Reduce the request size or try again later.", False),
            RunTimedOut: (504, "Try again later.", True),
            RunCancelled: (409, "Start a new run if you still need the result.", False),
        }.get(type(error), (500, "Try again later.", False))
        code = error.code
        message = translate_public_message(code, _safe_language_for_request(request))
        response = ApiResponse(success=False, data=None, message=message, processing_mode="agent",
            error=ApiError(code=code, message=message, action=action, retryable=retryable,
                           request_id=request.state.request_id, run_id=error.run_id or None))
        return JSONResponse(status_code=status_code, content=response.model_dump(), headers={"x-request-id": request.state.request_id})

    @app.exception_handler(Exception)
    async def handle_unknown_error(request: Request, _error: Exception) -> JSONResponse:
        message = translate_public_message("INTERNAL_ERROR", _safe_language_for_request(request))
        response = ApiResponse(success=False, data=None, message=message,
            error=ApiError(code="INTERNAL_ERROR", message=message, action="Try again later or contact support with the request ID.", request_id=request.state.request_id))
        return JSONResponse(status_code=500, content=response.model_dump(exclude={"processing_mode"}), headers={"x-request-id": request.state.request_id})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(agent_runs.router)
    app.include_router(account.router)
    app.include_router(settings_api.router)
    app.include_router(profile.router)
    app.include_router(profile_targets.router)
    app.include_router(food_catalog.router)
    app.include_router(meals.router)
    app.include_router(exercise_catalog.router)
    app.include_router(workouts.router)
    app.include_router(smart_entry.router)
    app.include_router(upload.router)
    app.include_router(calendar.router)
    app.include_router(today.router)
    app.include_router(coach.router)
    app.include_router(dashboard.router)
    app.include_router(chat.router)
    app.include_router(report.router)
    app.include_router(plan.router)
    app.include_router(eval.router)
    return app


app = create_app()
