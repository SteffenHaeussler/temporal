"""HTTP layer: start tickets, inspect status, approve or reject."""

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from temporalio.client import Client, WorkflowUpdateFailedError
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from ticketflow import config
from ticketflow.logging import reset_ticket_context, set_ticket_context, setup_logging
from ticketflow.models import ApprovalDecision, Ticket, TicketStatus, TicketStatusInfo
from ticketflow.workflows import TicketWorkflow

setup_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.temporal = await Client.connect(
        config.TEMPORAL_ADDRESS,
        namespace=config.TEMPORAL_NAMESPACE,
        data_converter=pydantic_data_converter,
    )
    yield


app = FastAPI(title="Ticketflow", lifespan=lifespan)


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


def _handle(ticket_id: str):
    return app.state.temporal.get_workflow_handle_for(
        TicketWorkflow.run, f"ticket-{ticket_id}"
    )


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
