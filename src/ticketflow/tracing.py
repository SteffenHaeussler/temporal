"""Application tracing configuration via OpenTelemetry."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.worker.workflow_sandbox import (
    SandboxedWorkflowRunner,
    SandboxRestrictions,
)

from ticketflow import config

SUPPORTED_EXPORTERS = {"none", "console", "otlp"}


def sandboxed_runner_with_otel() -> SandboxedWorkflowRunner:
    """Workflow sandbox that lets the tracing interceptor create spans."""
    return SandboxedWorkflowRunner(
        restrictions=SandboxRestrictions.default.with_passthrough_modules(
            "opentelemetry"
        )
    )


def setup_tracing(
    service_name: str,
    exporter: str | None = None,
    endpoint: str | None = None,
    span_exporter: SpanExporter | None = None,
) -> TracingInterceptor | None:
    """Configure OpenTelemetry and return the Temporal interceptor, if enabled.

    `span_exporter` overrides the configured exporter (used by tests); spans
    are then exported synchronously.
    """
    resolved_exporter = (exporter or config.TRACE_EXPORTER).lower()
    if resolved_exporter not in SUPPORTED_EXPORTERS:
        raise ValueError(f"Unsupported trace exporter: {resolved_exporter}")
    if span_exporter is None and resolved_exporter == "none":
        return None

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if span_exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    elif resolved_exporter == "console":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=endpoint or config.OTLP_ENDPOINT)
            )
        )

    # The global provider can only be set once per process; later setups
    # (e.g. repeated calls in tests) still trace via their own tracer below.
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        trace.set_tracer_provider(provider)

    return TracingInterceptor(tracer=provider.get_tracer("ticketflow"))
