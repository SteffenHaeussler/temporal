# Ticketflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Temporal.io learning project — a mocked AI support-ticket agent orchestrated by a durable workflow with conditional human-in-the-loop approval, driven through a FastAPI layer.

**Architecture:** One `TicketWorkflow` per ticket runs classify → draft → (conditional approval gate via signal + 24h timer) → execute. Activities wrap a swappable `Agent` protocol; a `MockAgent` provides realistic randomness. FastAPI starts workflows, queries status, and sends approval signals.

**Tech Stack:** Python 3.12+, `uv`, `temporalio` (with pydantic data converter), FastAPI, pytest + pytest-asyncio + Temporal time-skipping test environment.

**Conventions for every commit:** append this trailer to each commit message:

```
Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
```

**Note on tests:** `WorkflowEnvironment.start_time_skipping()` downloads a test-server binary on first run — the first `pytest` invocation needs internet access and may take ~30s.

## Task 4: MockAgent transient failures + determinism

**Files:**
- Modify: `src/ticketflow/agent/mock.py`
- Test: `tests/test_mock_agent.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_mock_agent.py`:

```python
import pytest

from ticketflow.agent.base import AgentOverloadedError


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
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/test_mock_agent.py -v`
Expected: `test_raises_transient_error_when_failure_rate_is_one` FAILS (`DID NOT RAISE`); the determinism tests pass already (they pin existing behavior — that is their job).

- [ ] **Step 3: Implement `_maybe_fail`**

In `src/ticketflow/agent/mock.py`, add the import and the failure check:

```python
from ticketflow.agent.base import AgentOverloadedError
```

Add to `MockAgent`:

```python
    def _maybe_fail(self) -> None:
        if self._rng.random() < self._failure_rate:
            raise AgentOverloadedError("mock agent backend overloaded")
```

Make `classify` call it first:

```python
    async def classify(self, ticket: Ticket) -> Classification:
        self._maybe_fail()
        text = f"{ticket.subject} {ticket.body}".lower()
        category = next(
            (cat for keyword, cat in KEYWORD_CATEGORIES.items() if keyword in text),
            TicketCategory.GENERAL,
        )
        return Classification(category=category, confidence=self._rng.uniform(0.5, 1.0))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mock_agent.py -v`
Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/ticketflow/agent/mock.py tests/test_mock_agent.py
git commit -m "feat: add seeded transient failures to mock agent"
```

---

## Task 5: MockAgent draft_reply with refund proposals

**Files:**
- Modify: `src/ticketflow/agent/mock.py`
- Test: `tests/test_mock_agent.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_mock_agent.py`:

```python
from ticketflow.models import ActionType


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mock_agent.py -v`
Expected: 2 FAIL — `AttributeError: 'MockAgent' object has no attribute 'draft_reply'`

- [ ] **Step 3: Implement `draft_reply`**

In `src/ticketflow/agent/mock.py`, extend the models import and add templates:

```python
from ticketflow.models import (
    ActionType,
    Classification,
    DraftReply,
    ProposedAction,
    Ticket,
    TicketCategory,
)

REPLY_TEMPLATES: dict[TicketCategory, str] = {
    TicketCategory.BILLING: (
        "Thanks for reaching out about your billing concern. "
        "I've reviewed your account and here is what I can do."
    ),
    TicketCategory.TECHNICAL: (
        "Sorry you hit a technical issue. Please try the steps below — "
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
```

Add the method to `MockAgent`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mock_agent.py -v`
Expected: 8 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/ticketflow/agent/mock.py tests/test_mock_agent.py
git commit -m "feat: mock agent drafts replies with random refund proposals"
```

---

## Task 6: Activities

**Files:**
- Create: `src/ticketflow/activities.py`
- Create: `tests/helpers.py`
- Test: `tests/test_activities.py`

- [ ] **Step 1: Create test helpers**

`tests/helpers.py` (scripted agent stubs implementing the `Agent` protocol — used by activity, workflow, and API tests):

```python
"""Test doubles and factories shared across test modules."""

import uuid

from ticketflow.agent.base import AgentOverloadedError
from ticketflow.models import (
    ActionType,
    Classification,
    DraftReply,
    ProposedAction,
    Ticket,
    TicketCategory,
)


def make_ticket(**overrides) -> Ticket:
    defaults = dict(
        id=uuid.uuid4().hex[:8],
        customer_email="jo@example.com",
        subject="Help",
        body="Something broke",
    )
    defaults.update(overrides)
    return Ticket(**defaults)


def billing_classification(confidence: float = 0.9) -> Classification:
    return Classification(category=TicketCategory.BILLING, confidence=confidence)


def refund_draft(amount: float = 42.0, confidence: float = 0.9) -> DraftReply:
    return DraftReply(
        reply_text="We can refund you.",
        action=ProposedAction(type=ActionType.REFUND, refund_amount=amount),
        confidence=confidence,
    )


def reply_only_draft(confidence: float = 0.9) -> DraftReply:
    return DraftReply(
        reply_text="Try restarting the app.",
        action=ProposedAction(type=ActionType.REPLY_ONLY),
        confidence=confidence,
    )


class ScriptedAgent:
    """Agent stub returning fixed responses; counts calls."""

    def __init__(self, classification: Classification, draft: DraftReply):
        self.classification = classification
        self.draft = draft
        self.classify_calls = 0
        self.draft_calls = 0

    async def classify(self, ticket: Ticket) -> Classification:
        self.classify_calls += 1
        return self.classification

    async def draft_reply(
        self, ticket: Ticket, classification: Classification
    ) -> DraftReply:
        self.draft_calls += 1
        return self.draft


class FlakyAgent:
    """Fails the first `failures` classify calls, then delegates to `inner`."""

    def __init__(self, inner: ScriptedAgent, failures: int):
        self.inner = inner
        self.remaining = failures
        self.classify_calls = 0

    async def classify(self, ticket: Ticket) -> Classification:
        self.classify_calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise AgentOverloadedError("flaky")
        return await self.inner.classify(ticket)

    async def draft_reply(
        self, ticket: Ticket, classification: Classification
    ) -> DraftReply:
        return await self.inner.draft_reply(ticket, classification)
```

- [ ] **Step 2: Write the failing tests**

`tests/test_activities.py` (uses `temporalio.testing.ActivityEnvironment` to run activities outside a workflow):

```python
from temporalio.testing import ActivityEnvironment

from tests.helpers import (
    ScriptedAgent,
    billing_classification,
    make_ticket,
    refund_draft,
)
from ticketflow.activities import TicketActivities


async def test_classify_ticket_delegates_to_agent():
    agent = ScriptedAgent(billing_classification(), refund_draft())
    acts = TicketActivities(agent)
    result = await ActivityEnvironment().run(acts.classify_ticket, make_ticket())
    assert result == agent.classification
    assert agent.classify_calls == 1


async def test_draft_reply_delegates_to_agent():
    agent = ScriptedAgent(billing_classification(), refund_draft())
    acts = TicketActivities(agent)
    result = await ActivityEnvironment().run(
        acts.draft_reply, make_ticket(), agent.classification
    )
    assert result == agent.draft
    assert agent.draft_calls == 1


async def test_side_effect_activities_complete():
    agent = ScriptedAgent(billing_classification(), refund_draft())
    acts = TicketActivities(agent)
    env = ActivityEnvironment()
    await env.run(acts.send_reply, make_ticket(), "hello")
    await env.run(acts.execute_refund, "t1", 42.0)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_activities.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ticketflow.activities'`

- [ ] **Step 4: Implement the activities**

`src/ticketflow/activities.py`:

```python
"""Activities wrap the agent and side effects — the only place non-determinism is allowed."""

from temporalio import activity

from ticketflow.agent.base import Agent
from ticketflow.models import Classification, DraftReply, Ticket


class TicketActivities:
    def __init__(self, agent: Agent):
        self._agent = agent

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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_activities.py -v`
Expected: 3 PASSED

- [ ] **Step 6: Commit**

```bash
git add src/ticketflow/activities.py tests/helpers.py tests/test_activities.py
git commit -m "feat: add ticket activities wrapping the agent"
```

---

## Task 7: TicketWorkflow — happy path + retry policy

**Files:**
- Create: `src/ticketflow/workflows.py`
- Modify: `tests/helpers.py` (add worker factory)
- Test: `tests/test_workflow.py`

- [ ] **Step 1: Add a worker factory to `tests/helpers.py`**

Append:

```python
from temporalio.client import Client
from temporalio.worker import Worker

from ticketflow.activities import TicketActivities
from ticketflow.agent.base import Agent


def make_worker(client: Client, agent: Agent, task_queue: str) -> Worker:
    acts = TicketActivities(agent)
    return Worker(
        client,
        task_queue=task_queue,
        workflows=[TicketWorkflow],
        activities=[
            acts.classify_ticket,
            acts.draft_reply,
            acts.send_reply,
            acts.execute_refund,
        ],
    )
```

Also add the import at the top of `tests/helpers.py`:

```python
from ticketflow.workflows import TicketWorkflow
```

- [ ] **Step 2: Write the failing tests**

`tests/test_workflow.py`:

```python
import uuid

import pytest
from temporalio.client import WorkflowFailureError

from tests.helpers import (
    FlakyAgent,
    ScriptedAgent,
    billing_classification,
    make_ticket,
    make_worker,
    reply_only_draft,
)
from ticketflow.models import TicketStatus
from ticketflow.workflows import TicketWorkflow


def unique_queue() -> str:
    return f"tq-{uuid.uuid4().hex[:8]}"


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
    assert agent.classify_calls == 3  # 2 failures + 1 success


async def test_workflow_fails_when_retries_are_exhausted(env):
    inner = ScriptedAgent(billing_classification(), reply_only_draft(confidence=0.9))
    agent = FlakyAgent(inner, failures=999)
    ticket = make_ticket()
    queue = unique_queue()
    async with make_worker(env.client, agent, queue):
        with pytest.raises(WorkflowFailureError):
            await env.client.execute_workflow(
                TicketWorkflow.run,
                ticket,
                id=f"ticket-{ticket.id}",
                task_queue=queue,
            )
    assert agent.classify_calls == 5  # maximum_attempts
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_workflow.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ticketflow.workflows'`

- [ ] **Step 4: Implement the minimal workflow (no approval gate yet)**

`src/ticketflow/workflows.py`:

```python
"""Durable per-ticket workflow."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ticketflow.activities import TicketActivities
    from ticketflow.models import (
        Classification,
        DraftReply,
        Ticket,
        TicketResult,
        TicketStatus,
    )

ACTIVITY_TIMEOUT = timedelta(seconds=30)
RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_attempts=5,
)


@workflow.defn
class TicketWorkflow:
    def __init__(self) -> None:
        self._status = TicketStatus.RECEIVED
        self._classification: Classification | None = None
        self._draft: DraftReply | None = None

    @workflow.run
    async def run(self, ticket: Ticket) -> TicketResult:
        self._status = TicketStatus.CLASSIFYING
        self._classification = await workflow.execute_activity_method(
            TicketActivities.classify_ticket,
            ticket,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )

        self._status = TicketStatus.DRAFTING
        self._draft = await workflow.execute_activity_method(
            TicketActivities.draft_reply,
            args=[ticket, self._classification],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )

        await workflow.execute_activity_method(
            TicketActivities.send_reply,
            args=[ticket, self._draft.reply_text],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        self._status = TicketStatus.RESOLVED
        return TicketResult(
            ticket_id=ticket.id,
            status=TicketStatus.RESOLVED,
            reply_text=self._draft.reply_text,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_workflow.py -v`
Expected: 3 PASSED (first run downloads the time-skipping test server)

Run: `uv run pytest`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add src/ticketflow/workflows.py tests/helpers.py tests/test_workflow.py
git commit -m "feat: add ticket workflow happy path with activity retries"
```

---

## Task 8: Approval gate — refund approved (signal + query)

**Files:**
- Modify: `src/ticketflow/workflows.py`
- Modify: `tests/helpers.py` (add status-polling helper)
- Test: `tests/test_workflow.py`

- [ ] **Step 1: Add a polling helper to `tests/helpers.py`**

Append:

```python
import asyncio

from temporalio.client import WorkflowHandle

from ticketflow.models import TicketStatus


async def wait_for_status(
    handle: WorkflowHandle, expected: TicketStatus, attempts: int = 100
):
    for _ in range(attempts):
        info = await handle.query(TicketWorkflow.status)
        if info.status == expected:
            return info
        await asyncio.sleep(0.1)
    raise AssertionError(f"workflow never reached status {expected}")
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_workflow.py`:

```python
from tests.helpers import refund_draft, wait_for_status
from ticketflow.models import ApprovalDecision


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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_workflow.py::test_approved_refund_executes_and_resolves -v`
Expected: FAIL — `AttributeError` (no `status` query / `submit_approval` signal on `TicketWorkflow`)

- [ ] **Step 4: Implement signal, query, and the approval gate**

Replace `src/ticketflow/workflows.py` with:

```python
"""Durable per-ticket workflow with conditional human approval."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ticketflow.activities import TicketActivities
    from ticketflow.models import (
        ActionType,
        ApprovalDecision,
        Classification,
        DraftReply,
        Ticket,
        TicketResult,
        TicketStatus,
        TicketStatusInfo,
    )

CONFIDENCE_THRESHOLD = 0.75
APPROVAL_TIMEOUT = timedelta(hours=24)
ACTIVITY_TIMEOUT = timedelta(seconds=30)
RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_attempts=5,
)

REJECTION_REPLY = (
    "Thanks for your patience. After review we cannot fulfil this request "
    "automatically; a human agent will follow up shortly."
)
ESCALATION_REPLY = (
    "We need a bit more time with your request and have escalated your "
    "ticket to a human agent."
)


@workflow.defn
class TicketWorkflow:
    def __init__(self) -> None:
        self._ticket: Ticket | None = None
        self._status = TicketStatus.RECEIVED
        self._classification: Classification | None = None
        self._draft: DraftReply | None = None
        self._decision: ApprovalDecision | None = None

    @workflow.run
    async def run(self, ticket: Ticket) -> TicketResult:
        self._ticket = ticket

        self._status = TicketStatus.CLASSIFYING
        self._classification = await workflow.execute_activity_method(
            TicketActivities.classify_ticket,
            ticket,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )

        self._status = TicketStatus.DRAFTING
        self._draft = await workflow.execute_activity_method(
            TicketActivities.draft_reply,
            args=[ticket, self._classification],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )

        needs_approval = (
            self._draft.action.type == ActionType.REFUND
            or self._draft.confidence < CONFIDENCE_THRESHOLD
        )
        if not needs_approval:
            return await self._finish(
                reply_text=self._draft.reply_text,
                refund=False,
                status=TicketStatus.RESOLVED,
            )

        self._status = TicketStatus.AWAITING_APPROVAL
        await workflow.wait_condition(
            lambda: self._decision is not None, timeout=APPROVAL_TIMEOUT
        )

        if not self._decision.approved:
            return await self._finish(
                reply_text=REJECTION_REPLY,
                refund=False,
                status=TicketStatus.REJECTED,
            )

        return await self._finish(
            reply_text=self._draft.reply_text,
            refund=self._draft.action.type == ActionType.REFUND,
            status=TicketStatus.RESOLVED,
        )

    @workflow.signal
    def submit_approval(self, decision: ApprovalDecision) -> None:
        self._decision = decision

    @workflow.query
    def status(self) -> TicketStatusInfo:
        return TicketStatusInfo(
            ticket_id=self._ticket.id if self._ticket else "",
            status=self._status,
            classification=self._classification,
            draft=self._draft,
            decision=self._decision,
        )

    async def _finish(
        self, *, reply_text: str, refund: bool, status: TicketStatus
    ) -> TicketResult:
        if refund:
            await workflow.execute_activity_method(
                TicketActivities.execute_refund,
                args=[self._ticket.id, self._draft.action.refund_amount],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RETRY_POLICY,
            )
        await workflow.execute_activity_method(
            TicketActivities.send_reply,
            args=[self._ticket, reply_text],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        self._status = status
        return TicketResult(
            ticket_id=self._ticket.id,
            status=status,
            reply_text=reply_text,
            refund_executed=refund,
        )
```

Note: the rejection branch in `run` and the timeout are not exercised yet — Tasks 9 and 10 pin them with tests. `wait_condition` raising `asyncio.TimeoutError` is intentionally unhandled for now.

- [ ] **Step 5: Run all tests to verify they pass**

Run: `uv run pytest -v`
Expected: all tests pass (happy path and retry tests still green)

- [ ] **Step 6: Commit**

```bash
git add src/ticketflow/workflows.py tests/helpers.py tests/test_workflow.py
git commit -m "feat: add approval gate with signal and status query"
```

---

## Task 9: Approval gate — rejection and low-confidence paths

**Files:**
- Modify: `src/ticketflow/workflows.py` (only if a test fails)
- Test: `tests/test_workflow.py`

- [ ] **Step 1: Write the tests**

Append to `tests/test_workflow.py`:

```python
from ticketflow.workflows import REJECTION_REPLY


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
    assert result.refund_executed is False  # reply-only action, no refund
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_workflow.py -v`
Expected: PASS — these pin behavior implemented in Task 8. If either fails, fix `workflows.py` (not the tests) until green.

- [ ] **Step 3: Commit**

```bash
git add tests/test_workflow.py
git commit -m "test: pin rejection and low-confidence approval paths"
```

---

## Task 10: Approval timeout → escalation

**Files:**
- Modify: `src/ticketflow/workflows.py`
- Test: `tests/test_workflow.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_workflow.py`:

```python
from ticketflow.workflows import ESCALATION_REPLY


async def test_unanswered_approval_escalates_after_timeout(env):
    agent = ScriptedAgent(billing_classification(), refund_draft())
    ticket = make_ticket()
    queue = unique_queue()
    async with make_worker(env.client, agent, queue):
        # No signal is ever sent; awaiting the result lets the time-skipping
        # environment jump past the 24h approval timeout instantly.
        result = await env.client.execute_workflow(
            TicketWorkflow.run,
            ticket,
            id=f"ticket-{ticket.id}",
            task_queue=queue,
        )

    assert result.status == TicketStatus.ESCALATED
    assert result.reply_text == ESCALATION_REPLY
    assert result.refund_executed is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_workflow.py::test_unanswered_approval_escalates_after_timeout -v`
Expected: FAIL — `WorkflowFailureError` caused by unhandled `asyncio.TimeoutError` from `wait_condition`

- [ ] **Step 3: Handle the timeout**

In `src/ticketflow/workflows.py`, wrap the `wait_condition` call:

```python
        self._status = TicketStatus.AWAITING_APPROVAL
        try:
            await workflow.wait_condition(
                lambda: self._decision is not None, timeout=APPROVAL_TIMEOUT
            )
        except asyncio.TimeoutError:
            return await self._finish(
                reply_text=ESCALATION_REPLY,
                refund=False,
                status=TicketStatus.ESCALATED,
            )
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `uv run pytest -v`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add src/ticketflow/workflows.py tests/test_workflow.py
git commit -m "feat: escalate tickets when approval times out after 24h"
```

---

## Task 11: FastAPI layer

**Files:**
- Create: `src/ticketflow/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_api.py` (drives the real workflow through the API using the time-skipping env; `ASGITransport` does not run the lifespan, so the test injects the env's client into `app.state`):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ticketflow.api'`

- [ ] **Step 3: Implement the API**

`src/ticketflow/api.py`:

```python
"""HTTP layer: start tickets, inspect status, approve/reject."""

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.service import RPCError

from ticketflow import config
from ticketflow.models import ApprovalDecision, Ticket, TicketStatusInfo
from ticketflow.workflows import TicketWorkflow


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.temporal = await Client.connect(
        config.TEMPORAL_ADDRESS, data_converter=pydantic_data_converter
    )
    yield


app = FastAPI(title="Ticketflow", lifespan=lifespan)


class CreateTicketRequest(BaseModel):
    customer_email: str
    subject: str
    body: str


class CreateTicketResponse(BaseModel):
    ticket_id: str


def _handle(ticket_id: str):
    return app.state.temporal.get_workflow_handle_for(
        TicketWorkflow.run, f"ticket-{ticket_id}"
    )


@app.post("/tickets", status_code=201)
async def create_ticket(request: CreateTicketRequest) -> CreateTicketResponse:
    ticket = Ticket(id=uuid.uuid4().hex[:8], **request.model_dump())
    await app.state.temporal.start_workflow(
        TicketWorkflow.run,
        ticket,
        id=f"ticket-{ticket.id}",
        task_queue=config.TASK_QUEUE,
    )
    return CreateTicketResponse(ticket_id=ticket.id)


@app.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: str) -> TicketStatusInfo:
    try:
        return await _handle(ticket_id).query(TicketWorkflow.status)
    except RPCError:
        raise HTTPException(status_code=404, detail="ticket not found")


@app.post("/tickets/{ticket_id}/approval")
async def submit_approval(ticket_id: str, decision: ApprovalDecision) -> dict:
    try:
        await _handle(ticket_id).signal(TicketWorkflow.submit_approval, decision)
    except RPCError:
        raise HTTPException(status_code=404, detail="ticket not found")
    return {"ok": True}
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `uv run pytest -v`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add src/ticketflow/api.py tests/test_api.py
git commit -m "feat: add FastAPI layer for tickets, status, and approvals"
```

---

## Task 12: Worker entrypoint + README runbook

**Files:**
- Create: `src/ticketflow/worker.py`
- Modify: `README.md`

- [ ] **Step 1: Write the worker entrypoint**

`src/ticketflow/worker.py`:

```python
"""Worker entrypoint: hosts the workflow and activities."""

import asyncio
import logging

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from ticketflow import config
from ticketflow.activities import TicketActivities
from ticketflow.agent.mock import MockAgent
from ticketflow.workflows import TicketWorkflow


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await Client.connect(
        config.TEMPORAL_ADDRESS, data_converter=pydantic_data_converter
    )
    acts = TicketActivities(MockAgent())
    worker = Worker(
        client,
        task_queue=config.TASK_QUEUE,
        workflows=[TicketWorkflow],
        activities=[
            acts.classify_ticket,
            acts.draft_reply,
            acts.send_reply,
            acts.execute_refund,
        ],
    )
    logging.info("Worker running on task queue %r", config.TASK_QUEUE)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Write the README**

Replace `README.md` with:

````markdown
# Ticketflow

A [Temporal.io](https://temporal.io) learning project: a mocked AI agent
resolves support tickets inside a durable workflow, with conditional
human-in-the-loop approval for refunds and low-confidence drafts.

Design doc: `docs/superpowers/specs/2026-06-10-ticketflow-design.md`

## Flow

```
POST /tickets ──▶ TicketWorkflow
                    classify ──▶ draft reply
                       │
        refund proposed OR confidence < 0.75?
              │ no                  │ yes
              ▼                     ▼
          send reply        wait for approval signal (max 24h)
          RESOLVED          ├─ approved ─▶ refund + reply ─▶ RESOLVED
                            ├─ rejected ─▶ fallback reply ─▶ REJECTED
                            └─ timeout  ─▶ escalation reply ─▶ ESCALATED
```

The agent is a `MockAgent` (random confidence, ~25% refund proposals, ~10%
transient failures that demonstrate activity retries). It sits behind the
`Agent` protocol in `src/ticketflow/agent/base.py` — swap in a real
LLM-backed implementation later.

## Run it

Prerequisites: [uv](https://docs.astral.sh/uv/), plus **one** of:

- the [Temporal CLI](https://docs.temporal.io/cli) (`brew install temporal`) → `make server`
- Docker → `make server-docker` (same dev server, containerized)

```bash
make install

make server   # terminal 1 — Temporal dev server (Web UI at http://localhost:8233)
              # (or: make server-docker, if you have Docker but not the Temporal CLI)
make worker   # terminal 2 — worker
make api      # terminal 3 — API
```

Then drive a ticket through (these wrap `curl` — see the Makefile):

```bash
# create a ticket (the mock agent is random — check the status to see
# which path you got; refund proposals trigger the approval gate)
make ticket
# => {"ticket_id": "<ID>"}

# inspect status (query against the running workflow)
make status ID=<ID>

# approve or reject (signal to the workflow)
make approve ID=<ID>
make reject ID=<ID>
```

Watch the workflow history — including retries of the mock agent's transient
failures and the pending approval timer — in the Web UI: http://localhost:8233

## Tests

```bash
uv run pytest
```

Workflow tests run against Temporal's time-skipping test environment, so the
"wait 24 hours for approval" path completes instantly. The first run downloads
a test-server binary — no Temporal CLI, server, or Docker needed for tests.
````

- [ ] **Step 3: Manual end-to-end smoke test**

1. `make server` (terminal 1)
2. `make worker` (terminal 2)
3. `make api` (terminal 3)
4. `make ticket`, then `make status ID=<ID>` until `awaiting_approval` (re-create tickets until the random mock proposes a refund), `make approve ID=<ID>`, confirm status `resolved`.
5. Open http://localhost:8233 and inspect the workflow history: activity retries (if the mock flaked), the signal, and the timer.

Expected: ticket reaches `resolved`; Web UI shows the full event history.

- [ ] **Step 4: Run the full test suite one last time**

Run: `uv run pytest`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add src/ticketflow/worker.py README.md
git commit -m "feat: add worker entrypoint and runbook"
```

---

## Future iterations (out of scope)

- Child `RefundWorkflow` with saga compensation
- Dynamic agent loop (agent picks the next step)
- Real Claude-backed `Agent` implementation
- Web UI on top of the API; Temporal Schedules for queue polling
