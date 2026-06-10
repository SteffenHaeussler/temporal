"""Mock agent with seedable classification randomness."""

import random

from ticketflow.models import Classification, Ticket, TicketCategory

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
