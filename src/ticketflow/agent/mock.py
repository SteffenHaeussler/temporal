"""Mock agent with seedable classification randomness."""

import random

from ticketflow.agent.base import AgentOverloadedError
from ticketflow.models import Classification, Ticket, TicketCategory

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
        self._maybe_fail()
        text = f"{ticket.subject} {ticket.body}".lower()
        category = next(
            (category for keyword, category in KEYWORD_CATEGORIES.items() if keyword in text),
            TicketCategory.GENERAL,
        )
        return Classification(
            category=category,
            confidence=self._rng.uniform(0.5, 1.0),
        )
