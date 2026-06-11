"""Wipe all ticketflow state: ticket workflows and the SQLite read model."""

from __future__ import annotations

import argparse
import asyncio

from temporalio.api.common.v1 import WorkflowExecution
from temporalio.api.workflowservice.v1 import request_response_pb2
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.service import RPCError

from ticketflow import config, readmodel

WORKFLOW_QUERY = 'WorkflowType = "TicketWorkflow"'
RUNNING_QUERY = WORKFLOW_QUERY + ' AND ExecutionStatus = "Running"'
TERMINATE_REASON = "ticketflow reset"


async def _terminate_running(client: Client) -> int:
    terminated = 0
    async for summary in client.list_workflows(RUNNING_QUERY):
        try:
            await client.get_workflow_handle(summary.id).terminate(
                reason=TERMINATE_REASON
            )
            terminated += 1
        except RPCError:
            pass
    return terminated


async def _wait_until_none_running(client: Client, timeout: float) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        async for _ in client.list_workflows(RUNNING_QUERY):
            break
        else:
            return
        await asyncio.sleep(0.5)


async def _delete_all(client: Client) -> int:
    deleted = 0
    async for summary in client.list_workflows(WORKFLOW_QUERY):
        try:
            # The Python SDK has no high-level delete; use the raw service.
            await client.workflow_service.delete_workflow_execution(
                request_response_pb2.DeleteWorkflowExecutionRequest(
                    namespace=client.namespace,
                    workflow_execution=WorkflowExecution(workflow_id=summary.id),
                )
            )
            deleted += 1
        except RPCError:
            pass
    return deleted


async def reset_workflows(
    client: Client, wait_timeout: float = 15.0
) -> tuple[int, int]:
    """Terminate running ticket workflows, then delete all of them.

    Deleting immediately after terminating races the server's close
    processing and parks the deletion in a slow retry loop, so we wait for
    visibility to show no running workflows before the delete pass.
    Individual failures (e.g. a workflow closing between listing and
    terminating) are skipped so a reset never aborts halfway.
    """
    terminated = await _terminate_running(client)
    if terminated:
        await _wait_until_none_running(client, wait_timeout)
    deleted = await _delete_all(client)
    return terminated, deleted


async def run_reset(client: Client, db_path: str | None = None) -> dict[str, int]:
    terminated, deleted = await reset_workflows(client)
    cleared = readmodel.clear(db_path)
    return {
        "terminated": terminated,
        "deleted": deleted,
        "read_model_rows_cleared": cleared,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Terminate and delete all ticket workflows and clear "
        "the SQLite read model."
    )
    parser.add_argument("--address", default=config.TEMPORAL_ADDRESS)
    parser.add_argument("--namespace", default=config.TEMPORAL_NAMESPACE)
    parser.add_argument("--db-path", default=config.DB_PATH)
    return parser.parse_args()


async def amain(args: argparse.Namespace) -> dict[str, int]:
    client = await Client.connect(
        args.address,
        namespace=args.namespace,
        data_converter=pydantic_data_converter,
    )
    return await run_reset(client, db_path=args.db_path)


def main() -> int:
    args = parse_args()
    try:
        summary = asyncio.run(amain(args))
    except RuntimeError as exc:
        print(f"reset failed: {exc}")
        return 1

    for key, value in summary.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
