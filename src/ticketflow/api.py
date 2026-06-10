"""HTTP layer: start tickets, inspect status, approve or reject."""

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.service import RPCError

from ticketflow import config
from ticketflow.models import ApprovalDecision, Ticket, TicketStatusInfo
from ticketflow.workflows import TicketWorkflow


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.temporal = await Client.connect(
        config.TEMPORAL_ADDRESS, data_converter=pydantic_data_converter
    )
    yield


app = FastAPI(title="Ticketflow", lifespan=lifespan)


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
    ticket = Ticket(id=uuid.uuid4().hex[:8], **request.model_dump())
    await app.state.temporal.start_workflow(
        TicketWorkflow.run,
        ticket,
        id=f"ticket-{ticket.id}",
        task_queue=config.TASK_QUEUE,
    )
    return CreateTicketResponse(ticket_id=ticket.id)


@app.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: str) -> TicketStatusInfo:
    try:
        return await _handle(ticket_id).query(TicketWorkflow.status)
    except RPCError as exc:
        raise HTTPException(status_code=404, detail="ticket not found") from exc


@app.post("/tickets/{ticket_id}/approval")
async def submit_approval(ticket_id: str, decision: ApprovalDecision) -> dict[str, bool]:
    try:
        await _handle(ticket_id).signal(TicketWorkflow.submit_approval, decision)
    except RPCError as exc:
        raise HTTPException(status_code=404, detail="ticket not found") from exc
    return {"ok": True}
