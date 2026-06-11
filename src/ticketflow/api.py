"""HTTP layer: start tickets, inspect status, approve or reject."""

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from temporalio.api.enums.v1 import task_queue_pb2
from temporalio.api.taskqueue.v1 import message_pb2 as taskqueue_pb2
from temporalio.api.workflowservice.v1 import request_response_pb2
from temporalio.client import Client, WorkflowUpdateFailedError
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from ticketflow import config
from ticketflow.logging import reset_ticket_context, set_ticket_context, setup_logging
from ticketflow.models import ApprovalDecision, Ticket, TicketStatus, TicketStatusInfo
from ticketflow.tracing import setup_tracing
from ticketflow.workflows import TicketWorkflow

setup_logging()
tracing_interceptor = setup_tracing(service_name="ticketflow-api")

logger = logging.getLogger(__name__)
READINESS_TIMEOUT = timedelta(seconds=2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.temporal = await Client.connect(
        config.TEMPORAL_ADDRESS,
        namespace=config.TEMPORAL_NAMESPACE,
        data_converter=pydantic_data_converter,
        interceptors=[tracing_interceptor] if tracing_interceptor else [],
    )
    yield


app = FastAPI(title="Ticketflow", lifespan=lifespan)

if tracing_interceptor:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)


@app.middleware("http")
async def ticket_context_middleware(request: Request, call_next):
    parts = request.url.path.strip("/").split("/")
    token = None
    if len(parts) >= 2 and parts[0] == "tickets" and parts[1]:
        token = set_ticket_context(parts[1])
    try:
        return await call_next(request)
    finally:
        if token is not None:
            reset_ticket_context(token)


class CreateTicketRequest(BaseModel):
    customer_email: str
    subject: str
    body: str


class CreateTicketResponse(BaseModel):
    ticket_id: str


class ListTicketsResponse(BaseModel):
    ticket_ids: list[str]


def _readiness_config() -> dict[str, str]:
    return {
        "address": config.TEMPORAL_ADDRESS,
        "namespace": config.TEMPORAL_NAMESPACE,
        "task_queue": config.TASK_QUEUE,
    }


def _handle(ticket_id: str):
    return app.state.temporal.get_workflow_handle_for(
        TicketWorkflow.run, f"ticket-{ticket_id}"
    )


async def _task_queue_poller_count(task_queue_type: int) -> int:
    request = request_response_pb2.DescribeTaskQueueRequest(
        namespace=config.TEMPORAL_NAMESPACE,
        task_queue=taskqueue_pb2.TaskQueue(name=config.TASK_QUEUE),
        task_queue_type=task_queue_type,
        report_pollers=True,
    )
    workflow_service = app.state.temporal.service_client.workflow_service
    response = await workflow_service.describe_task_queue(
        request, timeout=READINESS_TIMEOUT
    )
    return len(response.pollers)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "ticketflow-api"}


@app.get("/ready")
async def ready():
    try:
        temporal_healthy = await app.state.temporal.service_client.check_health(
            timeout=READINESS_TIMEOUT
        )
    except Exception:
        logger.warning("Temporal health check failed", exc_info=True)
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "temporal": {
                    "status": "unavailable",
                    "message": "Temporal server is not reachable. Run `make server`.",
                },
                "worker": {"status": "unknown"},
                "config": _readiness_config(),
            },
        )

    if not temporal_healthy:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "temporal": {
                    "status": "unavailable",
                    "message": "Temporal workflow service is not serving.",
                },
                "worker": {"status": "unknown"},
                "config": _readiness_config(),
            },
        )

    workflow_pollers = await _task_queue_poller_count(
        task_queue_pb2.TASK_QUEUE_TYPE_WORKFLOW
    )
    activity_pollers = await _task_queue_poller_count(
        task_queue_pb2.TASK_QUEUE_TYPE_ACTIVITY
    )
    worker_healthy = workflow_pollers > 0 and activity_pollers > 0
    worker = {
        "status": "healthy" if worker_healthy else "degraded",
        "task_queue": config.TASK_QUEUE,
        "workflow_pollers": workflow_pollers,
        "activity_pollers": activity_pollers,
    }
    if not worker_healthy:
        worker["message"] = "No worker pollers found. Run `make worker`."

    return {
        "status": "healthy" if worker_healthy else "degraded",
        "temporal": {"status": "healthy"},
        "worker": worker,
        "config": _readiness_config(),
    }


@app.post("/tickets", status_code=201)
async def create_ticket(request: CreateTicketRequest) -> CreateTicketResponse:
    ticket = Ticket(id=uuid.uuid4().hex, **request.model_dump())
    try:
        await app.state.temporal.start_workflow(
            TicketWorkflow.run,
            ticket,
            id=f"ticket-{ticket.id}",
            task_queue=config.TASK_QUEUE,
        )
    except WorkflowAlreadyStartedError as exc:
        raise HTTPException(status_code=409, detail="ticket already exists") from exc
    logger.info("Ticket workflow started", extra={"ticket_id": ticket.id})
    return CreateTicketResponse(ticket_id=ticket.id)


@app.get("/tickets")
async def list_tickets(status: TicketStatus) -> ListTicketsResponse:
    query = f'WorkflowType = "TicketWorkflow" and TicketStatus = "{status.value}"'
    ticket_ids = []
    async for workflow in app.state.temporal.list_workflows(query):
        workflow_id = workflow.id
        if workflow_id.startswith("ticket-"):
            ticket_ids.append(workflow_id.removeprefix("ticket-"))
    return ListTicketsResponse(ticket_ids=ticket_ids)


@app.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: str) -> TicketStatusInfo:
    try:
        return await _handle(ticket_id).query(TicketWorkflow.status)
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            raise HTTPException(status_code=404, detail="ticket not found") from exc
        raise


@app.post("/tickets/{ticket_id}/approval")
async def submit_approval(
    ticket_id: str, decision: ApprovalDecision
) -> dict[str, TicketStatus]:
    try:
        status = await _handle(ticket_id).execute_update(
            TicketWorkflow.submit_approval,
            decision,
            result_type=TicketStatus,
        )
    except WorkflowUpdateFailedError as exc:
        raise HTTPException(
            status_code=409, detail="ticket is not awaiting approval"
        ) from exc
    except RPCError as exc:
        if exc.status != RPCStatusCode.NOT_FOUND:
            raise
        # Updating a closed workflow is also NOT_FOUND; only the message
        # distinguishes it from a workflow id that never existed.
        message = exc.message.lower()
        if "completed" in message or (
            message.startswith("update ") and message.endswith(" not found")
        ):
            raise HTTPException(
                status_code=409, detail="ticket already decided"
            ) from exc
        raise HTTPException(status_code=404, detail="ticket not found") from exc
    return {"status": status}
