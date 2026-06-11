"""Connection settings shared by worker and API."""

import os

from dotenv import load_dotenv

load_dotenv(".env")

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")
TASK_QUEUE = os.environ.get("TICKETFLOW_TASK_QUEUE", "ticketflow")
