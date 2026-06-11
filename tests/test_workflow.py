import uuid

from tests.helpers import (
    FlakyAgent,
    ScriptedAgent,
    billing_classification,
    make_ticket,
    make_worker,
    refund_draft,
    reply_only_draft,
    wait_for_status,
)
from ticketflow.agent.base import AgentOverloadedError
from ticketflow.models import ApprovalDecision, TicketStatus
from ticketflow.workflows import ESCALATION_REPLY, REJECTION_REPLY, TicketWorkflow


def unique_queue() -> str:
    return f"tq-{uuid.uuid4().hex[:8]}"


class DraftFailingAgent:
    def __init__(self):
        self.classification = billing_classification()
        self.classify_calls = 0
        self.draft_calls = 0

    async def classify(self, ticket):
        self.classify_calls += 1
        return self.classification

    async def draft_reply(self, ticket, classification):
        self.draft_calls += 1
        raise AgentOverloadedError("draft unavailable")


async def test_high_confidence_reply_resolves_without_approval(env):
    agent = ScriptedAgent(billing_classification(), reply_only_draft(confidence=0.9))
    ticket = make_ticket()
    queue = unique_queue()
    async with make_worker(env.client, agent, queue):
        result = await env.client.execute_workflow(
            TicketWorkflow.run,
            ticket,
            id=f"ticket-{ticket.id}",
            task_queue=queue,
        )
    assert result.status == TicketStatus.RESOLVED
    assert result.reply_text == agent.draft.reply_text
    assert result.refund_executed is False


async def test_transient_agent_failures_are_retried(env):
    inner = ScriptedAgent(billing_classification(), reply_only_draft(confidence=0.9))
    agent = FlakyAgent(inner, failures=2)
    ticket = make_ticket()
    queue = unique_queue()
    async with make_worker(env.client, agent, queue):
        result = await env.client.execute_workflow(
            TicketWorkflow.run,
            ticket,
            id=f"ticket-{ticket.id}",
            task_queue=queue,
        )
    assert result.status == TicketStatus.RESOLVED
    assert agent.classify_calls == 3


async def test_workflow_escalates_when_classification_retries_are_exhausted(env):
    inner = ScriptedAgent(billing_classification(), reply_only_draft(confidence=0.9))
    agent = FlakyAgent(inner, failures=999)
    ticket = make_ticket()
    queue = unique_queue()
    async with make_worker(env.client, agent, queue):
        result = await env.client.execute_workflow(
            TicketWorkflow.run,
            ticket,
            id=f"ticket-{ticket.id}",
            task_queue=queue,
        )
    assert result.status == TicketStatus.ESCALATED
    assert result.reply_text == ESCALATION_REPLY
    assert result.refund_executed is False
    assert agent.classify_calls == 5


async def test_workflow_escalates_when_draft_retries_are_exhausted(env):
    agent = DraftFailingAgent()
    ticket = make_ticket()
    queue = unique_queue()
    async with make_worker(env.client, agent, queue):
        result = await env.client.execute_workflow(
            TicketWorkflow.run,
            ticket,
            id=f"ticket-{ticket.id}",
            task_queue=queue,
        )
    assert result.status == TicketStatus.ESCALATED
    assert result.reply_text == ESCALATION_REPLY
    assert result.refund_executed is False
    assert agent.classify_calls == 1
    assert agent.draft_calls == 5


async def test_approved_refund_executes_and_resolves(env):
    agent = ScriptedAgent(billing_classification(), refund_draft(amount=42.0))
    ticket = make_ticket()
    queue = unique_queue()
    async with make_worker(env.client, agent, queue):
        handle = await env.client.start_workflow(
            TicketWorkflow.run,
            ticket,
            id=f"ticket-{ticket.id}",
            task_queue=queue,
        )
        info = await wait_for_status(handle, TicketStatus.AWAITING_APPROVAL)
        assert info.draft is not None
        assert info.draft.action.refund_amount == 42.0

        await handle.signal(
            TicketWorkflow.submit_approval,
            ApprovalDecision(approved=True, note="ok, refund them"),
        )
        result = await handle.result()

    assert result.status == TicketStatus.RESOLVED
    assert result.refund_executed is True


async def test_rejected_refund_sends_fallback_reply(env):
    agent = ScriptedAgent(billing_classification(), refund_draft(amount=42.0))
    ticket = make_ticket()
    queue = unique_queue()
    async with make_worker(env.client, agent, queue):
        handle = await env.client.start_workflow(
            TicketWorkflow.run,
            ticket,
            id=f"ticket-{ticket.id}",
            task_queue=queue,
        )
        await wait_for_status(handle, TicketStatus.AWAITING_APPROVAL)
        await handle.signal(
            TicketWorkflow.submit_approval,
            ApprovalDecision(approved=False, note="amount looks wrong"),
        )
        result = await handle.result()

    assert result.status == TicketStatus.REJECTED
    assert result.reply_text == REJECTION_REPLY
    assert result.refund_executed is False


async def test_low_confidence_reply_requires_approval(env):
    agent = ScriptedAgent(billing_classification(), reply_only_draft(confidence=0.5))
    ticket = make_ticket()
    queue = unique_queue()
    async with make_worker(env.client, agent, queue):
        handle = await env.client.start_workflow(
            TicketWorkflow.run,
            ticket,
            id=f"ticket-{ticket.id}",
            task_queue=queue,
        )
        await wait_for_status(handle, TicketStatus.AWAITING_APPROVAL)
        await handle.signal(
            TicketWorkflow.submit_approval, ApprovalDecision(approved=True)
        )
        result = await handle.result()

    assert result.status == TicketStatus.RESOLVED
    assert result.refund_executed is False


async def test_unanswered_approval_escalates_after_timeout(env):
    agent = ScriptedAgent(billing_classification(), refund_draft())
    ticket = make_ticket()
    queue = unique_queue()
    async with make_worker(env.client, agent, queue):
        result = await env.client.execute_workflow(
            TicketWorkflow.run,
            ticket,
            id=f"ticket-{ticket.id}",
            task_queue=queue,
        )

    assert result.status == TicketStatus.ESCALATED
    assert result.reply_text == ESCALATION_REPLY
    assert result.refund_executed is False
