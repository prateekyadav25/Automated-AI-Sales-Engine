"""Optional OpenTelemetry. No-ops unless OTEL_EXPORTER_OTLP_ENDPOINT is set and the SDK is installed."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from app.core.logging import correlation_id_ctx, tenant_id_ctx


def setup_telemetry(app) -> None:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return

    provider = TracerProvider(resource=Resource.create({"service.name": "agrayian-api"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)


@contextmanager
def span(name: str, **attributes: str) -> Iterator[None]:
    try:
        from opentelemetry import trace
    except ImportError:
        yield
        return
    tracer = trace.get_tracer("agrayian")
    attrs = {
        "correlation_id": correlation_id_ctx.get() or "",
        "tenant_id": tenant_id_ctx.get() or "",
        **attributes,
    }
    with tracer.start_as_current_span(name, attributes=attrs):
        yield
