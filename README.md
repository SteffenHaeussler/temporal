# Ticketflow

Ticketflow is a Temporal.io learning project: a mocked AI support-ticket agent
will run inside a durable workflow with conditional human-in-the-loop approval.

The current scaffold includes the Python package, dependency setup, Temporal test
fixture, Makefile targets, and a Docker option for the Temporal dev server.
Later tasks add the data models, activities, workflow, worker, and FastAPI API.

## Requirements

- Python 3.12+
- `uv`
- Temporal CLI for `make server`, or Docker for `make server-docker`

## Setup

Install dependencies:

```bash
make install
```

Run the test suite:

```bash
make test
```

At this scaffold stage, pytest reports `no tests ran` and exits with code 5.
That is expected until the first tests are added in the next task.

## Temporal Dev Server

Run Temporal with the local CLI:

```bash
make server
```

Or run it with Docker:

```bash
make server-docker
```

Temporal listens on `localhost:7233`, and the Web UI is available at
`http://localhost:8233` when the dev server is running.

## Project Layout

```text
src/ticketflow/          Python package
src/ticketflow/config.py Shared Temporal address and task queue settings
tests/                   pytest suite and Temporal time-skipping fixture
docs/superpowers/specs/  design notes
```

## Planned Commands

The Makefile already includes targets for the worker, API, and ticket approval
flow. These targets are placeholders until later implementation tasks add the
corresponding modules:

```bash
make worker
make api
make ticket
make status ID=<ticket-id>
make approve ID=<ticket-id>
make reject ID=<ticket-id>
```
