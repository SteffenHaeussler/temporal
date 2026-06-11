import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from temporalio.client import Client
from temporalio.contrib.opentelemetry import TracingInterceptor

from tests.helpers import (
    ScriptedAgent,
    billing_classification,
    make_ticket,
    make_worker,
    reply_only_draft,
)
from ticketflow.tracing import sandboxed_runner_with_otel, setup_tracing
from ticketflow.workflows import TicketWorkflow


def test_invalid_exporter_raises_value_error():
    with pytest.raises(ValueError, match="Unsupported trace exporter"):
        setup_tracing(service_name="ticketflow-test", exporter="bogus")


def test_none_exporter_disables_tracing():
    assert setup_tracing(service_name="ticketflow-test", exporter="none") is None


def test_console_exporter_returns_interceptor():
    interceptor = setup_tracing(service_name="ticketflow-test", exporter="console")
    assert isinstance(interceptor, TracingInterceptor)


def test_injected_span_exporter_receives_spans_with_service_name():
    span_exporter = InMemorySpanExporter()
    interceptor = setup_tracing(
        service_name="ticketflow-test", span_exporter=span_exporter
    )
    assert isinstance(interceptor, TracingInterceptor)

    with interceptor.tracer.start_as_current_span("test-span"):
        pass

    spans = span_exporter.get_finished_spans()
    assert [span.name for span in spans] == ["test-span"]
    assert spans[0].resource.attributes["service.name"] == "ticketflow-test"


async def test_trace_has_span_for_each_workflow_step(env):
    span_exporter = InMemorySpanExporter()
    interceptor = setup_tracing(
        service_name="ticketflow-test", span_exporter=span_exporter
    )
    client_config = env.client.config()
    client_config["interceptors"] = [interceptor]
    client = Client(**client_config)

    agent = ScriptedAgent(billing_classification(), reply_only_draft())
    ticket = make_ticket()
    async with make_worker(
        client, agent, "tracing-queue", workflow_runner=sandboxed_runner_with_otel()
    ):
        await client.execute_workflow(
            TicketWorkflow.run,
            ticket,
            id=f"ticket-{ticket.id}",
            task_queue="tracing-queue",
        )

    spans = span_exporter.get_finished_spans()
    names = {span.name for span in spans}
    assert {
        "StartWorkflow:TicketWorkflow",
        "RunWorkflow:TicketWorkflow",
        "RunActivity:classify_ticket",
        "RunActivity:draft_reply",
        "RunActivity:send_reply",
    } <= names

    trace_ids = {span.context.trace_id for span in spans}
    assert len(trace_ids) == 1
