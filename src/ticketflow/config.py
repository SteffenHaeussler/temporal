"""Connection settings shared by worker and API."""

import os

from dotenv import load_dotenv

load_dotenv(".env")

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")
TASK_QUEUE = os.environ.get("TICKETFLOW_TASK_QUEUE", "ticketflow")
LOG_FORMAT = os.environ.get("TICKETFLOW_LOG_FORMAT", "text")
LOG_LEVEL = os.environ.get("TICKETFLOW_LOG_LEVEL", "INFO")
LOG_FIELDS = [
    field.strip()
    for field in os.environ.get(
        "TICKETFLOW_LOG_FIELDS", "time,level,logger,message,ticket_id"
    ).split(",")
    if field.strip()
]
