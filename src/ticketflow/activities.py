"""Activities wrap the agent and side effects."""

import asyncio

from temporalio import activity

from ticketflow import readmodel
from ticketflow.agent.base import Agent
from ticketflow.models import Classification, DraftReply, Ticket, TicketResult


class TicketActivities:
    def __init__(self, agent: Agent, db_path: str | None = None):
        self._agent = agent
        self._db_path = db_path

    @activity.defn
    async def classify_ticket(self, ticket: Ticket) -> Classification:
        return await self._agent.classify(ticket)

    @activity.defn
    async def draft_reply(
        self, ticket: Ticket, classification: Classification
    ) -> DraftReply:
        return await self._agent.draft_reply(ticket, classification)

    @activity.defn
    async def send_reply(self, ticket: Ticket, reply_text: str) -> None:
        activity.logger.info(
            "Sending reply to %s: %s", ticket.customer_email, reply_text
        )

    @activity.defn
    async def execute_refund(self, ticket_id: str, amount: float) -> None:
        # Idempotent by ticket id: a real implementation would use ticket_id
        # as the payment provider's idempotency key.
        activity.logger.info("Refunding %.2f for ticket %s", amount, ticket_id)

    @activity.defn
    async def record_result(self, result: TicketResult) -> None:
        await asyncio.to_thread(readmodel.save_result, result, self._db_path)
