import pytest

from ticketflow.agent.base import AgentOverloadedError
from ticketflow.agent.mock import MockAgent
from ticketflow.models import ActionType, Classification, Ticket, TicketCategory


def make_ticket(subject: str = "Help", body: str = "Something broke") -> Ticket:
    return Ticket(id="t1", customer_email="jo@example.com", subject=subject, body=body)


async def test_classifies_billing_by_keyword():
    agent = MockAgent(seed=1, failure_rate=0.0)

    result = await agent.classify(make_ticket(subject="Please refund my last charge"))

    assert result.category == TicketCategory.BILLING
    assert 0.5 <= result.confidence <= 1.0


async def test_classifies_technical_by_keyword():
    agent = MockAgent(seed=1, failure_rate=0.0)

    result = await agent.classify(make_ticket(body="the app shows an error and crashes"))

    assert result.category == TicketCategory.TECHNICAL


async def test_falls_back_to_general_category():
    agent = MockAgent(seed=1, failure_rate=0.0)

    result = await agent.classify(make_ticket(subject="hello", body="just saying hi"))

    assert result.category == TicketCategory.GENERAL


async def test_proposes_refund_when_refund_rate_is_one():
    agent = MockAgent(seed=1, failure_rate=0.0, refund_rate=1.0)
    ticket = make_ticket(subject="refund my charge")
    classification = await agent.classify(ticket)

    draft = await agent.draft_reply(ticket, classification)

    assert draft.action.type == ActionType.REFUND
    assert draft.action.refund_amount is not None
    assert draft.action.refund_amount > 0


async def test_reply_only_when_refund_rate_is_zero():
    agent = MockAgent(seed=1, failure_rate=0.0, refund_rate=0.0)
    ticket = make_ticket(body="the app crashes")
    classification = await agent.classify(ticket)

    draft = await agent.draft_reply(ticket, classification)

    assert draft.action.type == ActionType.REPLY_ONLY
    assert draft.action.refund_amount is None
    assert draft.reply_text
    assert 0.5 <= draft.confidence <= 1.0


async def test_draft_reply_raises_transient_error_when_failure_rate_is_one():
    agent = MockAgent(seed=1, failure_rate=1.0, refund_rate=0.0)
    ticket = make_ticket()
    classification = Classification(category=TicketCategory.GENERAL, confidence=1.0)

    with pytest.raises(AgentOverloadedError):
        await agent.draft_reply(ticket, classification)


async def test_raises_transient_error_when_failure_rate_is_one():
    agent = MockAgent(seed=1, failure_rate=1.0)

    with pytest.raises(AgentOverloadedError):
        await agent.classify(make_ticket())


async def test_never_fails_when_failure_rate_is_zero():
    agent = MockAgent(seed=1, failure_rate=0.0)

    for _ in range(50):
        await agent.classify(make_ticket())


async def test_same_seed_produces_same_classification():
    ticket = make_ticket(subject="refund please")
    a = MockAgent(seed=42, failure_rate=0.0)
    b = MockAgent(seed=42, failure_rate=0.0)

    assert await a.classify(ticket) == await b.classify(ticket)
