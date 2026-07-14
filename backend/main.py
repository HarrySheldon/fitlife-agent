from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.api import auth, calendar, chat, coach, dashboard, eval, health, plan, profile, report, settings as settings_api, today, upload
from backend.api.utils import application_error_response
from backend.config import get_settings
from backend.domain.errors import ApplicationError


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="FitLife Agent API", version="0.1.0")

    @app.exception_handler(ApplicationError)
    async def handle_application_error(_request: Request, error: ApplicationError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content=application_error_response(error),
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(settings_api.router)
    app.include_router(profile.router)
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
