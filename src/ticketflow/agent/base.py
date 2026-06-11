"""Agent interface for swappable ticket-resolution backends."""

from typing import Protocol

from ticketflow.models import Classification, DraftReply, Ticket


class AgentOverloadedError(Exception):
    """Transient failure simulating an overloaded LLM backend."""


class AgentPermanentError(Exception):
    """Permanent agent failure that should not be retried."""


class Agent(Protocol):
    async def classify(self, ticket: Ticket) -> Classification: ...

    async def draft_reply(
        self, ticket: Ticket, classification: Classification
    ) -> DraftReply: ...
