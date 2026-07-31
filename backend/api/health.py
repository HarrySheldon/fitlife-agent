import sqlite3

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.api.utils import ok
from backend.infrastructure.sqlite.runtime import get_database
from backend.infrastructure.startup import last_startup_summary


router = APIRouter()


@router.get("/health")
def health():
    return ok({"status": "ok"})


@router.get("/health/ready")
def readiness():
    try:
        with get_database().connection() as connection:
            quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
            schema_version = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
            failed_catalogs = connection.execute(
                "SELECT COUNT(*) FROM catalog_imports WHERE status = 'failed'"
            ).fetchone()[0]
            failed_legacy = connection.execute(
                """
                SELECT COUNT(*) FROM data_migrations
                WHERE migration_key LIKE 'legacy_csv_v1:%' AND status = 'failed'
                """
            ).fetchone()[0]
    except sqlite3.Error:
        payload = ok(
            {
                "status": "unavailable",
                "database": "unavailable",
                "schema_version": None,
                "failed_catalog_imports": None,
                "failed_legacy_migrations": None,
            }
        )
        return JSONResponse(status_code=503, content=payload)
    startup = last_startup_summary()
    if startup is not None:
        failed_catalogs = max(failed_catalogs, startup.catalog_failed)
        failed_legacy = max(failed_legacy, startup.legacy_failed)
    if quick_check != "ok":
        return JSONResponse(
            status_code=503,
            content=ok(
                {
                    "status": "unavailable",
                    "database": quick_check,
                    "schema_version": schema_version,
                    "failed_catalog_imports": failed_catalogs,
                    "failed_legacy_migrations": failed_legacy,
                }
            ),
        )
    status = "degraded" if failed_catalogs or failed_legacy else "ready"
    return ok(
        {
            "status": status,
            "database": quick_check,
            "schema_version": schema_version,
            "failed_catalog_imports": failed_catalogs,
            "failed_legacy_migrations": failed_legacy,
        }
    )
