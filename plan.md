# Ticketflow Current State

**Goal:** A Temporal.io learning project: a mocked AI support-ticket agent orchestrated by a durable workflow with conditional human-in-the-loop approval, driven through a FastAPI layer.

**Architecture:** One `TicketWorkflow` per ticket runs classify, draft, optional approval, and final side effects. Activities wrap a swappable `Agent` protocol; `MockAgent` provides realistic randomness. FastAPI starts workflows, queries status, and sends approval signals.

**Tech Stack:** Python 3.12+, `uv`, `temporalio` with the pydantic data converter, FastAPI, pytest, pytest-asyncio, pytest-cov, and Temporal's time-skipping test environment.

**Note on tests:** `WorkflowEnvironment.start_time_skipping()` downloads a test-server binary on first run. The first `pytest` invocation needs internet access and may take around 30 seconds.

## Implemented

- Activities wrap agent classification, drafting, reply sending, and refund execution.
- `TicketWorkflow` handles happy path replies, activity retries, approval signals, status queries, rejections, low-confidence approval, and approval timeout escalation.
- FastAPI exposes ticket creation, status lookup, and approval submission.
- Worker and README runbook are present.
- `make test` runs the normal pytest suite.
- `make coverage` runs pytest with terminal coverage and missing-line reporting.

## Future iterations (out of scope)

- Child `RefundWorkflow` with saga compensation
- Dynamic agent loop where the agent picks the next step
- Real Claude-backed `Agent` implementation
- Web UI on top of the API
- Temporal Schedules for queue polling
