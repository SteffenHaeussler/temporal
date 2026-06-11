# Ticketflow

A [Temporal.io](https://temporal.io) learning project: a mocked AI agent
resolves support tickets inside a durable workflow, with conditional
human-in-the-loop approval for refunds and low-confidence drafts.

Design doc: `docs/superpowers/specs/2026-06-10-ticketflow-design.md`

## Flow

```text
POST /tickets --> TicketWorkflow
                    classify --> draft reply
                       |
        refund proposed OR confidence < 0.75?
              | no                  | yes
              v                     v
          send reply        wait for approval signal (max 24h)
          RESOLVED          |- approved -> refund + reply -> RESOLVED
                            |- rejected -> fallback reply -> REJECTED
                            `- timeout  -> escalation reply -> ESCALATED
```

The agent is a `MockAgent` with random confidence, about 25% refund proposals,
and about 10% transient failures that demonstrate activity retries. It sits
behind the `Agent` protocol in `src/ticketflow/agent/base.py`; swap in a real
LLM-backed implementation later.

## Run It

Prerequisites: [uv](https://docs.astral.sh/uv/), plus one of:

- the Temporal CLI (`brew install temporal`) for `make server`
- Docker for `make server-docker`

```bash
make install

make server   # terminal 1: Temporal dev server, Web UI at http://localhost:8233
              # or: make server-docker
make worker   # terminal 2: workflow worker
make api      # terminal 3: FastAPI app
```

Then drive a ticket through:

```bash
make ticket
# => {"ticket_id": "<ID>"}

make status ID=<ID>

make approve ID=<ID>
make reject ID=<ID>
```

The mock agent is random. Check status to see which path a ticket took; refund
proposals and low-confidence drafts wait for approval.

Watch the workflow history, including retries, signals, and timers, in the
Temporal Web UI at http://localhost:8233.

## Tests

```bash
make check
make test
make coverage
```

Workflow tests run against Temporal's time-skipping test environment, so the
"wait 24 hours for approval" path completes instantly. The first run downloads
a test-server binary; no Temporal CLI, server, or Docker is needed for tests.

`make check` runs the local pre-PR gate: Ruff formatting check, Ruff linting,
and the normal test suite. `make install` also installs a pre-push hook that
runs `make check` automatically before a branch is pushed.

`make test` runs the normal suite. `make coverage` runs the same suite with a
terminal coverage report and missing-line details. Run `make format` to apply
Ruff formatting and import fixes locally.
