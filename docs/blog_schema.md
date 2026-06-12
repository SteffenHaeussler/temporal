# Blog Post Schema: Ticketflow

Working title ideas:
- *"A support ticket is not a request/response: durable execution, DDIA, and one
  small repo"*
- *"DDIA in the small: what 1,300 lines of Temporal taught me about distributed
  systems"*

Target: one post, ~2,500–3,500 words. Three pillars: **deployment**,
**DDIA**, **distributed computing**. Each section below has a thesis (write 1–2
paragraphs from it), the main points to make, the code to cite, and the DDIA
chapter it grounds. `docs/distributed-programming-arc.md` already contains prose
you can lift; `docs/context.md` has the decision reasoning.

---

## 1. Hook — the problem shape

**Thesis:** A support ticket is a terrible fit for a request/response handler:
it calls a flaky model, retries, waits up to 24 hours for a human, refunds
money, and must answer "where is it?" the entire time. The interesting part of
distributed systems is not the RPC — it's everything that happens *between*
requests.

**Main points:**
- Enumerate what one ticket needs: unreliable dependency, retries, a 24h human
  timer, an irreversible side effect (refund), status queries throughout.
- State the claim early: this is a learning repo, mocked LLM, dev server — the
  point is the behavior, not the product.

**Cite:** the flow diagram in `README.md`; `docs/superpowers/specs/2026-06-10-ticketflow-design.md` (the original decisions).

**DDIA:** ch. 1 (reliability, the questions data-intensive systems must answer).

---

## 2. Topology and deployment — how many services is this, really?

**Thesis:** The stack runs as four processes, but the irreducible minimum is
three: Temporal server, API, one worker. The fourth (the LLM worker) is an *ops
choice* — a separate failure domain for the scarce, rate-limited dependency.
Deployment topology is a decision you make, not a number you inherit.

**Main points:**
- The four roles: API edge (`api.py`), durable coordinator (Temporal server),
  workflow worker (`worker.py`), LLM worker (`llm_worker.py`).
- Why three is the minimum: one process can host every task queue —
  `llm_worker.py` already runs two `Worker` instances in one `asyncio.gather`
  (`src/ticketflow/llm_worker.py:64`). The split is for independent scaling and
  failure.
- **Failure-domain table** (write what breaks when each process dies):
  | process down | effect |
  |---|---|
  | API | no new tickets, no status reads; running tickets keep progressing |
  | workflow worker | tickets park as pending tasks; nothing is lost; resume on restart |
  | LLM worker | new agent calls wait 30s, then reroute to fallback — degraded, not down |
  | Temporal server | the actual outage: nothing starts, progresses, or answers |
- Probes that know the topology: `/ready` counts pollers on all three queues
  (`src/ticketflow/api.py:145-222`); `scripts/doctor.py` names the `make` target
  that fixes each gap.
- Containerizing surfaces a hidden dependency: API and worker share
  `ticketflow.db`, so compose needs a shared volume — the read model is part of
  the topology too (`docker-compose.yml`).
- Honesty paragraph: `start-dev` is a dev server; production Temporal
  (multi-node, real persistence) is out of scope, deliberately.

**Cite:** `docker-compose.yml`, `Dockerfile`, `src/ticketflow/api.py` (`/ready`),
`scripts/doctor.py`, `Makefile`.

**DDIA:** ch. 1 (fault vs failure: a dead worker is a fault the system
tolerates), ch. 8 (partial failure — processes fail independently).

---

## 3. Durable execution — the workflow as a replayed state machine

**Thesis:** Temporal lets workflow code look like normal control flow because it
is replayed from an event history. The discipline that buys: determinism in the
workflow, side effects exiled to activities, and state that survives any process
restart.

**Main points:**
- Walk `TicketWorkflow.run` top to bottom: classify → draft → maybe approval →
  finish (`src/ticketflow/workflows.py:68-141`). The fields `_status`, `_draft`,
  `_decision` are reconstructed by replay.
- The 24h wait costs no thread: `workflow.wait_condition(..., timeout=24h)` is a
  durable timer (`workflows.py:116-118`).
- Approval is a workflow **update with a validator**, not a signal: callers get
  a synchronous result or a 409; duplicates and late approvals are rejected
  *before* entering history (`workflows.py:143-159`, `api.py:305-333`; PR #21).
- A real race and its fix: `_finish` sets the terminal status *before* the final
  activities so a late approval can't slip in while escalation is finishing
  (`workflows.py:177-179`, PR #35). Frame: in workflow land, races are ordering
  bugs in one logical thread — fixed by sequencing, not locks.

**Cite:** `src/ticketflow/workflows.py`, `src/ticketflow/api.py`, PRs #21, #35.

**DDIA:** ch. 5/8 framing (state machine replication — deterministic code +
ordered event log = reproducible state), ch. 7 (the history as a write-ahead
log).

---

## 4. Timeouts, backpressure, and the fallback model

**Thesis:** "How long do I wait?" is three different questions in Temporal —
how long a task may *queue* (schedule-to-start), how long it may *run*
(start-to-close), and how often it must *prove liveness* (heartbeat). Each one
maps to a different production decision.

**Main points:**
- The timeout family on agent calls: `start_to_close=2m`, `heartbeat=30s`,
  `schedule_to_start=30s` (`workflows.py:32-37, 216-224`).
- The two rate-limit knobs and why they differ
  (`src/ticketflow/llm_worker.py:45-46`, `config.py:16-17`):
  server-side `max_task_queue_activities_per_second` = the vendor's budget,
  shared across the fleet; worker-side `max_concurrent_activities` = the host's
  capacity. Scaling workers never exceeds the vendor budget.
- Backpressure made visible: stop the LLM worker mid-batch → tickets park as
  pending activity tasks, resume on restart. Temporal's task queue *is* the
  message queue; no broker needed (decision log: "Split task queues").
- Fallback routing: a `SCHEDULE_TO_START` timeout means "the primary can't get
  to you in time" → rerun on the unthrottled fallback queue with a cheaper,
  lower-confidence model (`workflows.py:233-237, 264-276`,
  `mock.py:68-78`). Cost is visible: confidence ≤ 0.6 → more human approvals.
- The leaked abstraction (be honest): to catch the schedule-to-start timeout and
  switch queues, the workflow owns its retry loop (`maximum_attempts=1` + manual
  backoff, `workflows.py:216-246`) — retry state moved from platform to code.

**Cite:** `src/ticketflow/workflows.py`, `src/ticketflow/llm_worker.py`,
`src/ticketflow/config.py`, `src/ticketflow/agent/mock.py`, PRs #40, #43;
`make batch N=100` histograms (statuses + model_paths).

**DDIA:** ch. 8 (timeouts and unbounded delays — "how long is too long?"),
ch. 1 (load and overload), ch. 11's backpressure discussion.

---

## 5. DDIA in the small — three experiments

**Thesis:** Three textbook DDIA ideas were not just implemented but *provoked*:
break it on purpose, watch the failure mode, then let the design absorb it.

### 5a. Exactly-once = at-least-once + idempotency (ch. 7–8)

- The experiment: raise after the side effect on attempt 1 — the worker did the
  work, died before the ack, the server retried. History shows `attempt: 2`;
  SQLite shows one row.
- The ledger design: `refund_attempts` records every delivery (honest count, two
  rows), `refunds` records the effect at most once, keyed by ticket ID
  (`src/ticketflow/readmodel.py:44-65`, `activities.py:56-74`, PR #41).
- The counter-example: a plain `INSERT` + counter would have double-counted.
  Retries are routine; every non-idempotent side effect corrupts data the first
  time a worker dies in the gap between effect and ack.

### 5b. Payloads outlive code (ch. 4)

- The experiment: add a required field to `Classification` → replay of an open
  workflow's history hits a `ValidationError` → `WorkflowTaskFailed` loop. The
  workflow stays "Running" but its approval can never land (PR #39).
- The rule: add defaulted fields, never require/remove/rename. Required
  additions break backward compatibility (old histories); removals break forward
  compatibility (old senders). The live proof: `model: str = "primary"` defaults
  (`src/ticketflow/models.py:50,73,91`) with old-payload regression tests
  (`tests/test_models.py`).

### 5c. Derived data and two read paths (ch. 10–11)

- Live question ("which tickets await approval?") → `TicketStatus` search
  attribute, upserted on every transition (`workflows.py:248-250`), queried via
  the visibility store (`api.py:242-259`).
- Historical question ("what happened to ticket X?") → SQLite read model written
  once at terminal state, consulted when the live query can't answer:
  the `get_ticket` fallback chain (`api.py:262-302`) handles retention deletion,
  worker-down, and query timeout distinctly.
- Frame: workflow history is the system of record; SQLite is a derived view
  optimized for a different read. Same DDIA argument as materialized views and
  CQRS, at toy scale.

**Cite:** `docs/distributed-programming-arc.md` (both experiments are written up
there), `src/ticketflow/readmodel.py`, `src/ticketflow/models.py`,
`src/ticketflow/api.py`.

---

## 6. Where this would break in production

**Thesis:** The credibility section. A demo earns trust by knowing its own
edges — each of these is a known gap, stated as such (and two are drafted as
follow-ups in `docs/context.md`).

**Main points (one short paragraph each):**
- **Ceremonial heartbeats:** agent activities heartbeat only before/after the
  call (`activities.py:24-31`); a real LLM call >30s would trip
  `heartbeat_timeout`. Real fix: a periodic heartbeat loop.
- **No escape hatch on the fallback path:** the fallback activity has no
  schedule-to-start budget and the workflow no run timeout
  (`workflows.py:264-276`) — both LLM workers down means tickets hang, not
  escalate.
- **The manual retry loop** (from §4) — platform feature traded for routing
  control.
- **Dev-server deployment:** `start-dev`, single node; compose persists state to
  a volume but it is not production Temporal.
- **Floats for money** (`refund_amount: float`) and **no auth** on the approval
  endpoint — listed as out of scope from day one.

**DDIA:** ch. 1's closing point — reliability is about knowing your fault
assumptions.

---

## 7. Close

**Thesis:** The repo's one lesson: don't hide distribution behind a function
call. Make the long-running process explicit, store its history durably, exile
side effects to activities, give every transition a place in the model — and
then break it on purpose until you believe it.

- Callback to the hook: the ticket that waited 24 hours and still answered
  `GET /tickets/{id}` the whole time.
- Invitation: clone it, run `make up`, kill a worker mid-batch, watch.

---

## Assets to capture while writing

- [ ] Temporal Web UI: one workflow history showing retries (attempt 2+ on
      `classify_ticket`), the 24h timer, an `WorkflowExecutionUpdate` event.
- [ ] Web UI: the `WorkflowTaskFailed` loop from the schema-evolution experiment
      (re-provoke briefly or describe).
- [ ] `make batch N=100` output: status histogram + model_path histogram
      (primary vs fallback).
- [ ] Jaeger: one trace `POST /tickets` → `RunWorkflow` → activity spans.
- [ ] `sqlite3 ticketflow.db 'select * from refund_attempts'` next to
      `select * from refunds` after the crash experiment (2 attempts, 1 refund).
- [ ] `docker compose ps` of the running stack; `docker compose stop llm-worker`
      then a ticket falling back.

## Commit narrative (use as "how this evolved" anecdotes)

- #21 signal → update for approvals
- #33 the FastAPI/Temporal tracing-provider collision
- #35 the approval-timeout race
- #39 the schema-evolution break, provoked and fixed
- #40/#43 fallback queues and tuning
- #41 making refund idempotency observable

## Citation index (suggested reading order, mirrors the arc doc)

1. `README.md` — run it, watch one ticket.
2. `src/ticketflow/models.py` — the data crossing every boundary.
3. `src/ticketflow/api.py` — the edge: start, query, list, update.
4. `src/ticketflow/workflows.py` — the durable state machine (read slowly).
5. `src/ticketflow/activities.py` + `src/ticketflow/readmodel.py` — side
   effects and the idempotency ledger.
6. `src/ticketflow/worker.py` + `src/ticketflow/llm_worker.py` — the topology.
7. `tests/test_workflow.py` — the behaviors, time-skipped.
8. `docs/context.md` — why each decision was made.
