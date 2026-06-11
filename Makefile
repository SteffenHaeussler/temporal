.PHONY: install install-hooks lint format-check format check test coverage server server-docker jaeger worker api ticket status approve reject

install:
	uv sync
	uv run pre-commit install --hook-type pre-push

install-hooks:
	uv run pre-commit install --hook-type pre-push

lint:
	uv run ruff check .

format-check:
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .
	uv run ruff format .

check: format-check lint test

test:
	uv run pytest

coverage:
	uv run pytest --cov=ticketflow --cov-report=term-missing

## --- run the stack (one target per terminal) ---

server:
	temporal server start-dev

server-docker:
	docker compose up

jaeger:
	docker compose up jaeger

worker:
	uv run python -m ticketflow.worker

api:
	uv run uvicorn ticketflow.api:app --reload

## --- drive a ticket through (usage: make ticket / make status ID=abc123) ---

ticket:
	curl -s -X POST localhost:8000/tickets \
	  -H 'Content-Type: application/json' \
	  -d '{"customer_email": "jo@example.com", "subject": "refund please", "body": "I was double charged."}'

status:
	curl -s localhost:8000/tickets/$(ID)

approve:
	curl -s -X POST localhost:8000/tickets/$(ID)/approval \
	  -H 'Content-Type: application/json' \
	  -d '{"approved": true, "approver": "make", "note": "approved via make"}'

reject:
	curl -s -X POST localhost:8000/tickets/$(ID)/approval \
	  -H 'Content-Type: application/json' \
	  -d '{"approved": false, "approver": "make", "note": "rejected via make"}'
