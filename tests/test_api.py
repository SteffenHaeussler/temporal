import asyncio

from httpx import ASGITransport, AsyncClient

from tests.helpers import (
    ScriptedAgent,
    billing_classification,
    make_worker,
    refund_draft,
)
from ticketflow import config
from ticketflow.api import app
from ticketflow.models import TicketStatus


def http_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


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
