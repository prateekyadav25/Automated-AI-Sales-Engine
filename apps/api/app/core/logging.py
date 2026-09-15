import json
import logging
import re
import sys
from contextvars import ContextVar

correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="-")
tenant_id_ctx: ContextVar[str] = ContextVar("tenant_id", default="-")

_REDACT_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "client_secret",
    "private_key",
}
_SECRET_RE = re.compile(
    r"(bearer\s+[a-z0-9._\-]+|sk-[a-z0-9]+|eyj[a-z0-9_\-]+\.[a-z0-9_\-]+)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"\b\+?\d[\d\-\s()]{8,}\d\b")


def redact_text(value: str) -> str:
    redacted = _SECRET_RE.sub("[REDACTED]", value)
    redacted = _EMAIL_RE.sub("[EMAIL]", redacted)
    return _PHONE_RE.sub("[PHONE]", redacted)


def redact_mapping(data: dict) -> dict:
    out: dict = {}
    for key, value in data.items():
        if str(key).lower() in _REDACT_KEYS:
            out[key] = "[REDACTED]"
        elif isinstance(value, str):
            out[key] = redact_text(value)
        else:
            out[key] = value
    return out


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = redact_mapping(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(redact_text(a) if isinstance(a, str) else a for a in record.args)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "message": redact_text(record.getMessage()),
            "logger": record.name,
            "correlation_id": correlation_id_ctx.get(),
            "tenant_id": tenant_id_ctx.get(),
        }
        if record.exc_info:
            payload["exc"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
