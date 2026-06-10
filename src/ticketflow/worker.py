"""Worker entrypoint: hosts the workflow and activities."""

import asyncio
import logging

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from ticketflow import config
from ticketflow.activities import TicketActivities
from ticketflow.agent.mock import MockAgent
from ticketflow.workflows import TicketWorkflow


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await Client.connect(
        config.TEMPORAL_ADDRESS, data_converter=pydantic_data_converter
    )
    acts = TicketActivities(MockAgent())
    worker = Worker(
        client,
        task_queue=config.TASK_QUEUE,
        workflows=[TicketWorkflow],
        activities=[
            acts.classify_ticket,
            acts.draft_reply,
            acts.send_reply,
            acts.execute_refund,
        ],
    )
    logging.info("Worker running on task queue %r", config.TASK_QUEUE)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
