# Ticketflow Improvement Plan

Derived from the code review of the first iteration. Work top to bottom: each
phase builds on the previous one. Every task has **Why** (what it teaches),
**Steps** (check them off), and **Verify** (prove it works before moving on).

General verification loop for every task: `make test`, and for anything that
changes workflow behavior, drive a real ticket through with `make server` /
`make worker` / `make api` / `make ticket` and watch the event history in the
Web UI at http://localhost:8233.

---

## Phase 1 — Quick wins

### Task 1: Read config from the environment

**Why:** `src/ticketflow/config.py` hardcodes `localhost:7233`. Real deployments
point the same code at different Temporal clusters and namespaces via env vars.

**Steps:**
- [ ] In `config.py`, read `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, and
      `TICKETFLOW_TASK_QUEUE` from `os.environ` with the current values as defaults.
- [ ] Pass `namespace=` to both `Client.connect()` calls
      (`worker.py:18`, `api.py:19`).

**Verify:**
- [ ] `make test` still passes (tests use the time-skipping env, not the address).
- [ ] `TEMPORAL_ADDRESS=localhost:9999 make worker` fails to connect; unset works.

### Task 2: Full-UUID ticket IDs

**Why:** `api.py:46` uses `uuid.uuid4().hex[:8]` — 32 bits of entropy. By the
birthday bound, collisions become likely around √(2³²) ≈ 65k tickets. A
collision means `start_workflow` raises `WorkflowAlreadyStartedError` and the
new ticket is silently lost as a duplicate of an old one.

**Steps:**
- [ ] Use the full `uuid.uuid4().hex` (or `str(uuid.uuid4())`).
- [ ] Check `tests/helpers.py:24` (`make_ticket`) and align.

**Verify:**
- [ ] `make ticket` returns a long ID; `make status ID=<id>` still works.

### Task 3: Tighten the Pydantic models

**Why:** `models.py` accepts `confidence=7.3` or a REFUND action without an
amount. Validating at the model boundary removes the defensive `RuntimeError`
deep inside the workflow (`workflows.py:126`) — invalid data should fail when
it is *created*, not when it is *used*. Bonus: the pydantic data converter
enforces these constraints on every activity input/output crossing Temporal.

**Steps:**
- [ ] `Classification.confidence` and `DraftReply.confidence`:
      `Field(ge=0.0, le=1.0)`.
- [ ] `ProposedAction.refund_amount`: `Field(default=None, gt=0)`.
- [ ] Add a `@model_validator` on `ProposedAction`: `type == REFUND` requires
      `refund_amount` to be set.
- [ ] Simplify the now-impossible refund-amount guard in
      `TicketWorkflow._finish` (`workflows.py:126`).
- [ ] Add a small model test in `tests/test_models.py`
      (e.g. REFUND without amount raises `ValidationError`).

**Verify:**
- [ ] `make test`; new validation test passes.

---

## Phase 2 — Failure paths (core Temporal error semantics)

### Task 4: Escalate instead of fail when retries exhaust

**Why:** Today, if the agent stays down past 5 attempts, the whole workflow
fails (`test_workflow_fails_when_retries_are_exhausted` documents this). The
customer gets nothing and the ticket vanishes into the failed-workflows list.
In a ticket system, "fall back to a human" is the correct terminal state for
infrastructure failure — same as the approval timeout.

**Steps:**
- [ ] In `TicketWorkflow.run`, wrap the `classify_ticket` and `draft_reply`
      activity calls in `try/except temporalio.exceptions.ActivityError`.
- [ ] On failure, return via `self._finish(..., status=TicketStatus.ESCALATED)`
      with `ESCALATION_REPLY` (note: `send_reply` inside `_finish` can still
      run — it's a different activity with its own retries; think about
      whether you want a fallback if *that* also fails).
- [ ] Rewrite `test_workflow_fails_when_retries_are_exhausted` in
      `tests/test_workflow.py` to assert `ESCALATED` instead of
      `WorkflowFailureError` (reuse `FlakyAgent` with `failures=999`).

**Verify:**
- [ ] `make test`.
- [ ] In the Web UI, the workflow shows 5 failed activity attempts and still
      *completes* (green), ending in the escalation reply.

### Task 5: Learn the workflow-task-failure gotcha

**Why:** In the Python SDK, a plain `RuntimeError` raised in workflow code does
**not** fail the workflow — it fails the *workflow task*, which Temporal
retries forever, so the workflow silently hangs. Only
`temporalio.exceptions.ApplicationError` (or activity/timeout failures)
actually fail the workflow. This is one of the most surprising Temporal
behaviors; provoke it once on purpose.

**Steps:**
- [ ] Experiment: temporarily `raise RuntimeError("boom")` at the top of
      `_finish`, run a ticket, and watch the Web UI — the workflow stays
      "Running" with repeating `WorkflowTaskFailed` events. Revert.
- [ ] Replace the remaining `RuntimeError`s in `_finish` (`workflows.py:124`)
      with `ApplicationError(..., non_retryable=True)`.

**Verify:**
- [ ] You saw the infinite `WorkflowTaskFailed` loop with your own eyes.
- [ ] `make test` after the revert + `ApplicationError` change.

### Task 6: Precise API error handling

**Why:** `api.py:60` and `api.py:68` map *every* `RPCError` to 404 — a Temporal
outage masquerades as "ticket not found". Signaling a completed ticket and
re-creating an existing ticket also deserve honest status codes.

**Steps:**
- [ ] In both handlers, only return 404 when
      `exc.status == temporalio.service.RPCStatusCode.NOT_FOUND`; re-raise
      otherwise (FastAPI turns it into a 500, which is the truth).
- [ ] In the approval handler, map "workflow already completed" to 409 with a
      message like "ticket already decided" (inspect what the dev server
      returns for a signal to a closed workflow — check `exc.status` and
      `exc.message` in a quick experiment).
- [ ] In `create_ticket`, catch
      `temporalio.exceptions.WorkflowAlreadyStartedError` → 409.
- [ ] Add tests: approval on a resolved ticket → 409 (run a high-confidence
      ticket to completion first, reuse `ScriptedAgent` +
      `reply_only_draft(confidence=0.9)`).

**Verify:**
- [ ] `make test`; manually: approve the same ticket twice via `make approve`,
      second call returns 409.

---

## Phase 3 — HITL v2

### Task 7: Convert the approval signal to a workflow update

**Why:** Signals are fire-and-forget: a duplicate or mistimed approval is
silently dropped and the API caller never learns whether it counted. An
**update** is the modern HITL primitive — it has a *validator* (reject before
it ever hits history) and returns a synchronous result to the caller. This is
the single biggest Temporal learning item in this plan.

**Steps:**
- [ ] Replace `@workflow.signal submit_approval` with `@workflow.update`
      (it can return e.g. the resulting `TicketStatus` or an ack model).
- [ ] Add the validator via `@submit_approval.validator`: raise unless
      `self._status == TicketStatus.AWAITING_APPROVAL` and
      `self._decision is None`. Validators must be synchronous, must not
      mutate state, and rejections leave no trace in history.
- [ ] API: call `handle.execute_update(TicketWorkflow.submit_approval, decision)`
      and surface a rejected update as 409.
- [ ] Update tests in `tests/test_workflow.py` / `tests/test_api.py`; add a
      duplicate-approval test (second update is rejected) and an
      approval-before-awaiting test if you can race one (optional).
- [ ] Read the event history in the Web UI: find `WorkflowExecutionUpdate*`
      events and compare with the old signal events.

**Verify:**
- [ ] `make test`; `make approve` now returns the new status synchronously;
      a second `make approve` returns 409.

### Task 8: Record who approved

**Why:** A refund approval without an approver identity is useless for audit.
The decision is already durably stored in workflow history — make it complete.

**Steps:**
- [ ] Add `approver: str` to `ApprovalDecision` (`models.py:53`).
- [ ] Thread it through the Makefile curl payloads and tests.

**Verify:**
- [ ] `make test`; `make status ID=<id>` on a decided ticket shows the approver.

---

## Phase 4 — Visibility & scaling

### Task 9: Batch driver — ~100 tickets

**Why:** Everything so far is one ticket at a time. 100 concurrent tickets make
scale visible: the worker drains a real task-queue backlog, the 10% mock
failure rate produces visible activity retries across histories, and ~60
tickets (25% refund + ~50% low-confidence) park at AWAITING_APPROVAL —
demonstrating why the approval inbox (next task) is needed. Also a reusable
load driver for later tasks.

**Steps:**
- [ ] Add `scripts/batch.py`: async `httpx.AsyncClient` (httpx is already a
      dev dependency, visible to `uv run`) that POSTs N tickets (default 100)
      to `localhost:8000/tickets`, bounded by `asyncio.Semaphore(10)`.
- [ ] Vary subject/body by sampling from a small pool hitting the mock agent's
      keywords (`agent/mock.py:16` — e.g. "refund", "crash", "password", and
      one keyword-free entry) so all four categories appear.
- [ ] Then poll `GET /tickets/{id}` until every ticket reaches a settled state
      (`resolved`, `escalated`, `rejected`, or `awaiting_approval`), with an
      overall timeout; print a status histogram
      (e.g. `resolved: 38, awaiting_approval: 62`).
- [ ] Makefile: `N ?= 100` and a `batch` target running
      `uv run python scripts/batch.py --count $(N)`; add `batch` to `.PHONY`.

**Verify:**
- [ ] With server/worker/api running: `make batch` prints a histogram summing
      to 100, roughly ~40% resolved / ~60% awaiting_approval.
- [ ] Web UI shows ~100 `ticket-*` workflows; spot-check one with failed
      activity attempts that still completed.
- [ ] `make batch N=10` works for a quick run.

### Task 10: Search attributes + approval inbox

**Why:** There is no way to list tickets, especially "everything awaiting
approval" — at scale, humans can't find what to approve. Queries won't help
(they hit one workflow at a time and need a live worker). The Temporal answer
is the **visibility store**: workflows upsert *search attributes*, clients
filter with `list_workflows`.

**Steps:**
- [ ] Register a custom search attribute on the dev server (one-time, add a
      Makefile target):
      `temporal operator search-attribute create --name TicketStatus --type Keyword`
- [ ] In the workflow, define
      `STATUS_ATTR = SearchAttributeKey.for_keyword("TicketStatus")` and call
      `workflow.upsert_search_attributes([STATUS_ATTR.value_set(status)])`
      wherever `self._status` changes (a tiny `_set_status` helper avoids
      repeating yourself).
- [ ] API: add `GET /tickets?status=awaiting_approval` using
      `client.list_workflows('TicketStatus = "awaiting_approval"')`; return
      ticket IDs (strip the `ticket-` prefix from workflow IDs).
- [ ] Note for tests: the time-skipping test server needs the attribute
      registered too — `WorkflowEnvironment.start_time_skipping(search_attributes=...)`
      supports this; if it gets fiddly, cover the inbox endpoint manually and
      keep automated tests for the rest.

**Verify:**
- [ ] Start two refund tickets (or run `make batch N=10` from Task 9),
      `curl 'localhost:8000/tickets?status=awaiting_approval'` lists the
      waiting ones; approve one, it drops out (visibility is eventually
      consistent — allow a second).
- [ ] In the Web UI, filter workflows by `TicketStatus`.

### Task 11 (stretch): Read model that survives retention

**Why:** `GET /tickets/{id}` is a workflow query: it dies when the workflow's
history is deleted after the retention period, and querying *closed* workflows
forces a worker to replay history. Production systems persist ticket state
outside Temporal.

**Steps:**
- [ ] Add a `record_result` activity that writes the final `TicketResult` to a
      tiny SQLite table (stdlib `sqlite3` is fine for learning).
- [ ] Call it from `_finish` after `send_reply`.
- [ ] `GET /tickets/{id}`: try the workflow query first; on NOT_FOUND, fall
      back to the read model.

**Verify:**
- [ ] Resolve a ticket, stop the worker, `make status` still answers from the DB.

---

## Phase 5 — Ops learning experiments (throwaway, but do them)

### Task 12: Provoke and fix a nondeterminism error

**Why:** With 24h approval timers there are *always* open workflows during a
deploy. Any change to workflow code breaks replay for them. You should see
this error once in a sandbox before it finds you in production.

**Steps:**
- [ ] Start a refund ticket so it parks at AWAITING_APPROVAL. Stop the worker.
- [ ] Edit `TicketWorkflow.run` to add a new activity call *before* the wait
      (e.g. a second `send_reply`). Restart the worker, then `make approve`.
- [ ] Observe the nondeterminism failure in worker logs / Web UI.
- [ ] Fix it with `if workflow.patched("pre-wait-notify"):` gating the new
      call, restart, approve again — the old workflow completes on the old
      path while new tickets take the new one.
- [ ] Read up on the lifecycle: `patched` → `deprecate_patch` → remove.
- [ ] Revert the experiment.

**Verify:**
- [ ] You saw the nondeterminism error and resolved it with `patched()`.

### Task 13: Make the activities real-LLM-ready (sketch)

**Why:** The 30s `start_to_close_timeout` and blanket retry policy fit the
mock, not a real LLM backend (slow calls, rate limits, permanent vs transient
errors).

**Steps:**
- [ ] Split activity options: agent activities get a longer
      `start_to_close_timeout` (e.g. 2–5 min) plus a `heartbeat_timeout`, and
      call `activity.heartbeat()` inside long agent calls.
- [ ] Distinguish errors: keep retrying `AgentOverloadedError`, but raise
      `ApplicationError(..., non_retryable=True)` (or list types in
      `RetryPolicy.non_retryable_error_types`) for permanent failures like
      invalid input.
- [ ] Sketch (in a `docs/` note, no need to build): a separate task queue for
      agent activities with its own worker and
      `max_concurrent_activities` tuned to the LLM rate limit, so workflow
      progress and LLM throughput scale independently.

**Verify:**
- [ ] `make test`; a `FlakyAgent`-style test showing a non-retryable error
      goes straight to the escalation path without 5 attempts.

---

## Deliberately out of scope (for now)

- Auth on the approval endpoint (anyone can approve refunds today).
- Real notification on ESCALATED — it's currently just a status + reply.
- Payment-provider idempotency for refunds (the code comment in
  `activities.py:31` already marks the spot).
- Production Temporal deployment (the docker-compose `start-dev` is
  ephemeral SQLite; fine for learning).
