.PHONY: install test server server-docker worker api ticket status approve reject

install:
	uv sync

test:
	uv run pytest

## --- run the stack (one target per terminal) ---

server:
	temporal server start-dev

server-docker:
	docker compose up

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
	  -d '{"approved": true, "note": "approved via make"}'

reject:
	curl -s -X POST localhost:8000/tickets/$(ID)/approval \
	  -H 'Content-Type: application/json' \
	  -d '{"approved": false, "note": "rejected via make"}'
