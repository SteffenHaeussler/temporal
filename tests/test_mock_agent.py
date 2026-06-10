from ticketflow.agent.mock import MockAgent
from ticketflow.models import Ticket, TicketCategory


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
