import asyncio
import uuid

from httpx import ASGITransport, AsyncClient

from tests.helpers import (
    ScriptedAgent,
    billing_classification,
    make_ticket,
    make_worker,
    refund_draft,
    reply_only_draft,
)
from ticketflow import config
from ticketflow.api import CreateTicketRequest, app, create_ticket
from ticketflow.models import TicketStatus
from ticketflow.workflows import TicketWorkflow


def http_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class RecordingTemporalClient:
    def __init__(self) -> None:
        self.workflow_id: str | None = None

    async def start_workflow(self, _workflow, ticket, *, id: str, task_queue: str):
        self.workflow_id = id
        assert id == f"ticket-{ticket.id}"
        assert task_queue == config.TASK_QUEUE


async def test_create_ticket_uses_full_uuid_hex_id():
    temporal = RecordingTemporalClient()
    app.state.temporal = temporal

    response = await create_ticket(
        CreateTicketRequest(
            customer_email="jo@example.com",
            subject="refund please",
            body="I was double charged.",
        )
    )

    assert len(response.ticket_id) == 32
    int(response.ticket_id, 16)
    assert temporal.workflow_id == f"ticket-{response.ticket_id}"


async def test_ticket_lifecycle_via_api(env):
    app.state.temporal = env.client
    agent = ScriptedAgent(billing_classification(), refund_draft(amount=42.0))
    async with make_worker(env.client, agent, config.TASK_QUEUE):
        async with http_client() as http:
            created = await http.post(
                "/tickets",
                json={
                    "customer_email": "jo@example.com",
                    "subject": "refund please",
                    "body": "I was double charged.",
                },
            )
            assert created.status_code == 201
            ticket_id = created.json()["ticket_id"]

            for _ in range(100):
                status = await http.get(f"/tickets/{ticket_id}")
                assert status.status_code == 200
                if status.json()["status"] == TicketStatus.AWAITING_APPROVAL:
                    break
                await asyncio.sleep(0.1)
            else:
                raise AssertionError("ticket never reached awaiting_approval")

            approved = await http.post(
                f"/tickets/{ticket_id}/approval",
                json={"approved": True, "note": "looks good"},
            )
            assert approved.status_code == 200
            assert approved.json() == {"status": TicketStatus.RESOLVED}

            for _ in range(100):
                status = await http.get(f"/tickets/{ticket_id}")
                if status.json()["status"] == TicketStatus.RESOLVED:
                    break
                await asyncio.sleep(0.1)
            else:
                raise AssertionError("ticket never resolved")


async def test_unknown_ticket_returns_404(env):
    app.state.temporal = env.client
    async with http_client() as http:
        response = await http.get("/tickets/does-not-exist")
    assert response.status_code == 404


async def test_approval_on_unknown_ticket_returns_404(env):
    app.state.temporal = env.client
    async with http_client() as http:
        response = await http.post(
            "/tickets/does-not-exist/approval",
            json={"approved": True},
        )
    assert response.status_code == 404


async def test_approval_on_resolved_ticket_returns_409(env):
    app.state.temporal = env.client
    agent = ScriptedAgent(billing_classification(), reply_only_draft(confidence=0.9))
    async with make_worker(env.client, agent, config.TASK_QUEUE):
        ticket = make_ticket()
        handle = await env.client.start_workflow(
            TicketWorkflow.run,
            ticket,
            id=f"ticket-{ticket.id}",
            task_queue=config.TASK_QUEUE,
        )
        result = await handle.result()
        assert result.status == TicketStatus.RESOLVED

        async with http_client() as http:
            response = await http.post(
                f"/tickets/{ticket.id}/approval",
                json={"approved": True, "note": "too late"},
            )
    assert response.status_code == 409
    assert response.json()["detail"] == "ticket already decided"


async def test_create_existing_ticket_returns_409(env, monkeypatch):
    app.state.temporal = env.client
    ticket = make_ticket()
    await env.client.start_workflow(
        TicketWorkflow.run,
        ticket,
        id=f"ticket-{ticket.id}",
        task_queue=config.TASK_QUEUE,
    )

    # Patching uuid4 globally also fixes the request_id the Temporal SDK
    # generates per start call, so only one POST may happen under the patch:
    # a second would be deduplicated as a retry instead of rejected.
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(hex=ticket.id))
    async with http_client() as http:
        response = await http.post(
            "/tickets",
            json={
                "customer_email": ticket.customer_email,
                "subject": ticket.subject,
                "body": ticket.body,
            },
        )
    assert response.status_code == 409
