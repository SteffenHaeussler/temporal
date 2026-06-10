"""Mock agent with seedable classification randomness."""

import random

from ticketflow.agent.base import AgentOverloadedError
from ticketflow.models import (
    ActionType,
    Classification,
    DraftReply,
    ProposedAction,
    Ticket,
    TicketCategory,
)

# Multiple keywords can indicate the same support category.
KEYWORD_CATEGORIES: dict[str, TicketCategory] = {
    "refund": TicketCategory.BILLING,
    "money": TicketCategory.BILLING,
    "charge": TicketCategory.BILLING,
    "invoice": TicketCategory.BILLING,
    "crash": TicketCategory.TECHNICAL,
    "error": TicketCategory.TECHNICAL,
    "bug": TicketCategory.TECHNICAL,
    "password": TicketCategory.ACCOUNT,
    "login": TicketCategory.ACCOUNT,
}

REPLY_TEMPLATES: dict[TicketCategory, str] = {
    TicketCategory.BILLING: (
        "Thanks for reaching out about your billing concern. "
        "I've reviewed your account and here is what I can do."
    ),
    TicketCategory.TECHNICAL: (
        "Sorry you hit a technical issue. Please try the steps below - "
        "we've also flagged this to our engineers."
    ),
    TicketCategory.ACCOUNT: (
        "Thanks for contacting us about your account. "
        "I've checked your account settings and here is how to proceed."
    ),
    TicketCategory.GENERAL: (
        "Thanks for your message! Here is some information that should help."
    ),
}


class MockAgent:
    def __init__(
        self,
        seed: int | None = None,
        failure_rate: float = 0.1,
        refund_rate: float = 0.25,
    ):
        self._rng = random.Random(seed)
        self._failure_rate = failure_rate
        self._refund_rate = refund_rate

    def _maybe_fail(self) -> None:
        if self._rng.random() < self._failure_rate:
            raise AgentOverloadedError("mock agent backend overloaded")

    async def classify(self, ticket: Ticket) -> Classification:
        text = f"{ticket.subject} {ticket.body}".lower()
        category = next(
            (category for keyword, category in KEYWORD_CATEGORIES.items() if keyword in text),
            TicketCategory.GENERAL,
        )
        return Classification(
            category=category,
            confidence=self._rng.uniform(0.5, 1.0),
        )

    async def draft_reply(
        self, ticket: Ticket, classification: Classification
    ) -> DraftReply:
        self._maybe_fail()
        if self._rng.random() < self._refund_rate:
            action = ProposedAction(
                type=ActionType.REFUND,
                refund_amount=round(self._rng.uniform(5.0, 100.0), 2),
            )
        else:
            action = ProposedAction(type=ActionType.REPLY_ONLY)
        return DraftReply(
            reply_text=REPLY_TEMPLATES[classification.category],
            action=action,
            confidence=self._rng.uniform(0.5, 1.0),
        )
