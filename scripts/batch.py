"""Create and monitor a batch of Ticketflow tickets."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable

import httpx

SETTLED_STATUSES = {"resolved", "escalated", "rejected", "awaiting_approval"}
TRANSIENT_STATUS_CODES = {500, 502, 503, 504}

KEYWORD_TEMPLATES = [
    {
        "subject": "Refund request for duplicate charge",
        "body": "I need a refund because my card shows the same charge twice.",
    },
    {
        "subject": "App crash when opening report",
        "body": "The dashboard shows an error and then the app crashes.",
    },
    {
        "subject": "Password reset login help",
        "body": "I cannot login after changing my password.",
    },
    {
        "subject": "Question about account options",
        "body": "I would like to understand which plan is right for our team.",
    },
]


class BatchTimeoutError(RuntimeError):
    """Raised when a batch does not settle before the timeout."""


def make_ticket_payloads(count: int) -> list[dict[str, str]]:
    """Build varied ticket creation payloads for a batch run."""
    payloads = []
    for index in range(count):
        template = KEYWORD_TEMPLATES[index % len(KEYWORD_TEMPLATES)]
        payloads.append(
            {
                "customer_email": f"batch-{index + 1}@example.com",
                "subject": f"{template['subject']} #{index + 1}",
                "body": template["body"],
            }
        )
    return payloads


async def create_tickets(
    client: httpx.AsyncClient,
    payloads: Iterable[dict[str, str]],
    *,
    concurrency: int,
) -> list[str]:
    """Create tickets concurrently and return their ids."""
    semaphore = asyncio.Semaphore(concurrency)

    async def create_one(payload: dict[str, str]) -> str:
        async with semaphore:
            response = await client.post("/tickets", json=payload)
            response.raise_for_status()
            return str(response.json()["ticket_id"])

    return await asyncio.gather(*(create_one(payload) for payload in payloads))


async def poll_ticket_statuses(
    client: httpx.AsyncClient,
    ticket_ids: Iterable[str],
    *,
    timeout: float,
    poll_interval: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict[str, str]:
    """Poll tickets until every id reaches a settled status."""
    pending = set(ticket_ids)
    statuses: dict[str, str] = {}
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    while pending:
        if loop.time() >= deadline:
            waiting = ", ".join(sorted(pending))
            raise BatchTimeoutError(f"Timed out waiting for tickets: {waiting}")

        for ticket_id in sorted(pending):
            try:
                response = await client.get(f"/tickets/{ticket_id}")
            except httpx.TimeoutException:
                continue
            if response.status_code in TRANSIENT_STATUS_CODES:
                continue
            response.raise_for_status()
            status = str(response.json()["status"])
            statuses[ticket_id] = status
            if status in SETTLED_STATUSES:
                pending.remove(ticket_id)

        if pending:
            await sleep(poll_interval)

    return statuses


def status_histogram(statuses: dict[str, str]) -> dict[str, int]:
    """Summarize settled statuses and include the total ticket count."""
    counts = Counter(statuses.values())
    histogram = {status: counts[status] for status in sorted(counts)}
    histogram["total"] = len(statuses)
    return histogram


async def run_batch(
    *,
    count: int,
    base_url: str,
    concurrency: int,
    timeout: float,
) -> dict[str, int]:
    """Create a batch of tickets and return the settled status histogram."""
    payloads = make_ticket_payloads(count)
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        ticket_ids = await create_tickets(client, payloads, concurrency=concurrency)
        statuses = await poll_ticket_statuses(
            client,
            ticket_ids,
            timeout=timeout,
        )
    return status_histogram(statuses)


def print_histogram(histogram: dict[str, int]) -> None:
    """Print a status histogram in CLI-friendly form."""
    for status, count in histogram.items():
        print(f"{status}: {count}")


def parse_args() -> argparse.Namespace:
    """Parse batch driver command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Create many Ticketflow tickets and print a status histogram."
    )
    parser.add_argument("--count", type=_positive_int, default=100)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--concurrency", type=_positive_int, default=10)
    parser.add_argument("--timeout", type=_positive_float, default=120.0)
    return parser.parse_args()


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def main() -> int:
    """Run the batch driver command."""
    args = parse_args()
    try:
        histogram = asyncio.run(
            run_batch(
                count=args.count,
                base_url=args.base_url,
                concurrency=args.concurrency,
                timeout=args.timeout,
            )
        )
    except (BatchTimeoutError, httpx.HTTPError) as exc:
        print(f"batch failed: {exc}")
        return 1

    print_histogram(histogram)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
