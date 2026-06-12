# Ticketflow Improvement Plan

Remaining work from the code-review improvement plan. Completed phases have
been removed; only open tasks are listed. Every task has **Why** (what it
teaches), **Steps** (check them off), and **Verify** (prove it works before
moving on).

General verification loop for every task: `make test`, and for anything that
changes workflow behavior, drive a real ticket through with `make server` /
`make worker` / `make api` / `make ticket` and watch the event history in the
Web UI at http://localhost:8233.

---

## Open tasks

### Task 1: Concurrent batch polling

**Why:** `poll_ticket_statuses` (`scripts/batch.py:134`) checks pending
tickets one at a time, so a 100-ticket batch pays 100 sequential round trips
per polling pass. Ticket *creation* already uses bounded concurrency
(`asyncio.Semaphore`, `scripts/batch.py:104`) — polling should too.

**Steps:**
- [x] Check pending ticket statuses concurrently with bounded concurrency,
      reusing the `asyncio.Semaphore` pattern from `create_tickets`.
- [x] Keep the existing semantics: transient errors leave the ticket pending,
      settled statuses remove it, the overall deadline still raises
      `BatchTimeoutError`.
- [x] Update the batch script's unit tests for the concurrent path.

**Verify:**
- [x] `make test`.
- [ ] With server/worker/api running: `make batch N=100` completes with a
      histogram summing to 100, noticeably faster polling passes.

### Task 2: Honest `GET /tickets` failure when the search attribute is missing

**Why:** `list_tickets` (`src/ticketflow/api.py:206`) queries the visibility
store via the `TicketStatus` search attribute. On a fresh dev server where
`make search-attributes` was never run, the query fails opaquely. The batch
script already preflights this (`scripts/batch.py:62`); the API endpoint
should fail just as helpfully.

**Steps:**
- [ ] Catch the RPC error raised when `TicketStatus` is not registered and
      return an actionable response (e.g. 503 with "search attribute
      TicketStatus is not registered — run `make search-attributes`").
- [ ] Add an API test for the missing-attribute path.

**Verify:**
- [ ] `make test`.
- [ ] Manually: against a dev server without the attribute registered,
      `curl 'localhost:8000/tickets?status=awaiting_approval'` returns the
      guidance instead of a bare 500.

### Task 3: Rate-limited agent task queue

**Why:** `make batch` starts 100 tickets and the instant mock agent drains
them in seconds — nothing about the system feels rate-limited. Real LLM
backends are: the provider grants a request budget shared by your whole
worker fleet. Temporal's task queue *is* the messaging queue; the realistic
experience comes from capacity tuning, not from adding a broker. This builds
the `docs/agent-activity-ops.md` sketch for real and teaches the two
production knobs and why they differ:

- `max_task_queue_activities_per_second` (server-side) models the
  *dependency's* limit — enforced across all workers, scaling workers never
  exceeds the vendor budget.
- `max_concurrent_activities` (worker-side) models the *host's* capacity —
  per-process protection, tuned on every production worker.

**Steps:**
- [ ] Config (`config.py`): `TICKETFLOW_AGENT_TASK_QUEUE` (default
      `ticketflow-agent`), `AGENT_MAX_PER_SECOND` (default `10.0` for local
      batch demos), `AGENT_MAX_CONCURRENT` (default `20`),
      `MOCK_AGENT_LATENCY_MAX_S`
      (default `0` so tests stay instant).
- [ ] `MockAgent`: add a `latency_range: tuple[float, float]` and sleep a
      seeded-random duration inside `classify`/`draft` (where the heartbeat
      from Task 13 already fires). Seeded RNG, like the failure injection.
- [ ] New `llm_worker.py` entrypoint: polls the agent queue, registers only
      `classify_ticket` and `draft_reply`, sets
      `max_concurrent_activities=AGENT_MAX_CONCURRENT` and
      `max_task_queue_activities_per_second=AGENT_MAX_PER_SECOND`, and runs
      `MockAgent` with realistic latency.
- [ ] `worker.py`: stop registering the two agent activities; keep
      `TicketWorkflow` and the fast activities (`send_reply`,
      `execute_refund`, `record_result`).
- [ ] `TicketWorkflow.run`: pass `task_queue=AGENT_TASK_QUEUE` in the activity
      options for `classify_ticket` and `draft_reply`. Note: this changes
      replay for open workflows — the Task 12 nondeterminism lesson applies;
      use a clean slate (`make reset`) or gate with `workflow.patched()`.
- [ ] Makefile: `llm-worker` target (with `MOCK_AGENT_LATENCY_MAX_S=3`);
      add to `.PHONY`; mention it next to `make worker` in the README run
      instructions.
- [ ] `scripts/doctor.py`: also check for pollers on the agent queue so a
      forgotten `make llm-worker` is diagnosed, not a silent hang.
- [ ] Tests: workflow test asserting agent activities run on the agent queue;
      existing tests keep instant mocks (latency defaults to 0).
- [ ] Update `docs/agent-activity-ops.md` from sketch to implemented notes.

**Verify:**
- [ ] `make test`.
- [ ] Full stack (`make server` / `make worker` / `make llm-worker` /
      `make api`): `make batch N=100` — the agent queue drains under the
      local demo defaults while `send_reply` stays instant; histogram still
      sums to 100.
- [ ] Start a *second* `make llm-worker`: the combined drain rate stays
      capped at `AGENT_MAX_PER_SECOND` (server-side limit shared across
      workers); stop it and the rate is unchanged.
- [ ] Stop `make llm-worker` entirely mid-batch: tickets park with pending
      activity tasks (visible backpressure), then resume when it restarts.

### Task 4: Fallback model via schedule-to-start timeout

**Depends on:** Task 3 (two-queue setup with rate-limited agent queue).

**Why:** Real LLM stacks fall back to a cheaper/faster model when the primary
can't respond in time. The Temporal-shaped version of "in time" is
`schedule_to_start_timeout` — the budget for how long an activity task may
*wait in the queue* before it's worth rerouting. The normal local defaults are
tuned so `make batch N=100` mostly stays on the primary path; lower
`AGENT_MAX_PER_SECOND` when you want to demonstrate fallback under load. This
also completes the timeout family: `start_to_close` (Task 13), `heartbeat`
(Task 13), and now `schedule_to_start`. Deliberately *not* building: provider
registries or config-driven fallback chains — two agents, no abstraction.

**Steps:**
- [ ] Add a fallback `MockAgent` flavor: fast (no/low latency), un-throttled,
      but returns *lower confidence* (e.g. cap at 0.6) so the cost of falling
      back is visible downstream — more tickets land in the approval inbox.
- [ ] Config: `TICKETFLOW_FALLBACK_TASK_QUEUE` (default
      `ticketflow-agent-fallback`) and `AGENT_SCHEDULE_TO_START_S`
      (default `30`).
- [ ] Host the fallback agent: either a third small entrypoint or a second
      `Worker` in `llm_worker.py`'s asyncio task group — pick whichever
      reads cleaner; no rate limit on the fallback queue.
- [ ] In `TicketWorkflow.run`: call `classify_ticket`/`draft_reply` on the
      primary agent queue with
      `schedule_to_start_timeout=AGENT_SCHEDULE_TO_START_S`; catch the
      `ActivityError` whose cause is a `TimeoutError` of type
      `SCHEDULE_TO_START` and retry the same activity on the fallback queue.
      Other failures keep the existing escalation path from Task 4 (old plan).
- [ ] Record which path served the ticket (e.g. a `model: str` or
      `fallback: bool` field on `Classification`/`DraftReply`) so the
      histogram and `make status` show it.
- [ ] Tests: a workflow test where the primary queue has no worker →
      schedule-to-start fires → fallback answers with low confidence and the
      ticket parks at AWAITING_APPROVAL; existing happy-path tests unchanged.

**Verify:**
- [ ] `make test`.
- [ ] Full stack with both LLM workers and a deliberately low
      `AGENT_MAX_PER_SECOND`: `make batch N=100` — early tickets resolve via
      the primary, later ones (queue wait > 30s) come back fast via the
      fallback with lower confidence; the approval inbox grows accordingly.
      Inspect one fallback ticket's history: the `SCHEDULE_TO_START` timeout,
      then the activity on the fallback queue.
- [ ] Stop only the primary LLM worker: every new ticket falls back after
      30s instead of hanging — degraded service, not an outage.

### Task 5: Provoke and fix a payload schema-evolution break (DDIA ch. 4)

**Why:** Task 12 (old plan) covered evolving workflow *code* under replay;
this is its data twin. Pydantic models cross the Temporal wire on every
activity call, and replay deserializes payloads recorded in history with
*today's* models — payloads outlive code by up to the retention period.
Adding a required field to a model breaks replay for every open workflow,
with the same silent symptom as the Task 5 (old plan) lesson: the workflow
hangs in a `WorkflowTaskFailed` loop. The production rule to internalize:
**add optional fields, never remove, rename, or require** — the payload
analog of `workflow.patched()`. Throwaway experiment, like Task 12.

**Steps:**
- [x] Start a refund ticket so it parks at AWAITING_APPROVAL (its history now
      contains a `classify_ticket` result with the *old* schema). Stop the
      worker.
- [x] Add a required field to `Classification` in `models.py` (e.g.
      `language: str`) and supply it in `MockAgent.classify` so new payloads
      are valid.
- [x] Restart the worker, `make approve`. Replay decodes the old
      `ActivityTaskCompleted` payload with the new model → `ValidationError`
      → workflow task failure. Observe the `WorkflowTaskFailed` loop in the
      Web UI / worker logs: the workflow stays "Running", the approval never
      lands.
- [x] Fix forward: give the field a default (`language: str = "en"`).
      Restart, approve again — the old payload now validates and the ticket
      resolves.
- [x] Note the asymmetry in a short `docs/` note: required-field *additions*
      break old histories (backward compatibility), removals break any
      consumer still sending them (forward compatibility); defaults buy you
      both.
- [x] Revert the experiment.

**Verify:**
- [x] You saw the replay `ValidationError` loop with your own eyes, and the
      defaulted field resolved it without touching history.
- [x] `make test` after the revert.

### Task 6: Prove at-least-once delivery and idempotent side effects (DDIA ch. 7–8)

**Why:** Temporal activities are at-least-once: if the worker finishes the
side effect but dies before acking the completion, the activity *runs again*.
"Exactly-once" in real systems is at-least-once delivery plus idempotent
effects. The code already claims this — `readmodel.save_result` is an
`INSERT OR REPLACE` upsert and `execute_refund` documents idempotency by
ticket ID — but the property has never been demonstrated. Provoke the
duplicate run once and watch the idempotency absorb it.

**Steps:**
- [x] Inject a crash *after* the side effect, *before* the ack: in
      `record_result`, after `save_result`, temporarily
      `raise RuntimeError("crash after side effect")` when
      `activity.info().attempt == 1`.
- [x] Resolve a high-confidence ticket. In the Web UI: attempt 1 fails
      *after* writing to SQLite, the retry policy schedules attempt 2, the
      write runs again, the upsert absorbs it.
- [x] Confirm effectively-once: exactly one row for the ticket in
      `ticket_results` (`sqlite3 ticketflow.db 'select count(*) ...'`), and
      `make status` returns the correct terminal result.
- [x] Make the refund's idempotency observable instead of a comment: record
      refund attempts keyed by `ticket_id` (e.g. a tiny
      `refund_attempts` table or log line with the attempt number) and rerun
      the crash experiment on `execute_refund` — second attempt is a no-op,
      "one refund" survives the duplicate run.
- [x] Counter-example to feel the danger: imagine the write were
      `INSERT` + counter increment instead of an upsert — the duplicate run
      would double-count. Note in one sentence why retries make
      non-idempotent side effects corrupt data.
- [x] Revert the injected crash.

**Verify:**
- [x] You saw an activity succeed at its side effect, fail, retry, and leave
      exactly one logical result behind.
- [x] `make test` after the revert.

---

## Deliberately out of scope (for now)

- Auth on the approval endpoint (anyone can approve refunds today).
- Real notification on ESCALATED — it's currently just a status + reply.
- Payment-provider idempotency for refunds (the code comment in
  `activities.py:31` already marks the spot).
- Production Temporal deployment (the docker-compose `start-dev` is
  ephemeral SQLite; fine for learning).
