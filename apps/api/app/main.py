import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging, correlation_id_ctx
from app.core.telemetry import setup_telemetry
from app.db.session import get_engine
from app.schemas.common import Envelope, ErrorBody
from app.services.provider_metrics import HTTP_REQUESTS

configure_logging()
settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0")
setup_telemetry(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.middleware("http")
async def correlation_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    cid = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    correlation_id_ctx.set(cid)
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.webhook_max_body_bytes * 4:
        return JSONResponse(status_code=413, content={"error": {"code": "payload_too_large", "message": "Payload too large"}})
    response = await call_next(request)
    HTTP_REQUESTS.labels(method=request.method, status=str(response.status_code)).inc()
    response.headers["X-Correlation-ID"] = cid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=Envelope(
            error=ErrorBody(code="validation_error", message="Invalid request", details=exc.errors())
        ).model_dump(),
    )


def _live() -> dict:
    return {
        "status": "ok",
        "service": "api",
        "app_name": settings.app_name,
        "version": "0.1.0",
        "environment": settings.environment,
    }


def _ready() -> dict:
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        if engine.dialect.name == "postgresql":
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            if not revision:
                raise HTTPException(status_code=503, detail="Database schema is not migrated")
    return {
        "status": "ready",
        "service": "api",
        "app_name": settings.app_name,
        "version": "0.1.0",
        "environment": settings.environment,
    }


@app.get("/health")
def health() -> dict:
    return _live()


@app.get("/health/live")
def health_live() -> dict:
    return _live()


@app.get("/ready")
def ready() -> dict:
    return _ready()


@app.get("/health/ready")
def health_ready() -> dict:
    return _ready()


@app.get("/metrics")
def metrics(
    authorization: str | None = Header(default=None),
) -> Response:
    token = settings.metrics_token
    if settings.is_production and not token:
        raise HTTPException(status_code=404, detail="Not found")
    if token:
        expected = f"Bearer {token}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
