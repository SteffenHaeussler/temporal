# Agent Activity Operations Sketch

Real LLM-backed activities should run on a separate task queue from workflow
progress and lightweight side effects.

Recommended shape:

- Keep `TicketWorkflow` on the existing `ticketflow` task queue.
- Move `classify_ticket` and `draft_reply` to an `ticketflow-agent` task queue
  served by a dedicated worker process.
- Tune that worker's `max_concurrent_activities` to the LLM provider rate
  limit, not to API or workflow throughput.
- Leave `send_reply`, `execute_refund`, and `record_result` on the normal
  worker so tickets can keep progressing when the LLM queue is saturated.

The agent activities should keep longer start-to-close timeouts and heartbeat
timeouts than side-effect activities. Transient provider pressure should raise
`AgentOverloadedError` and retry. Permanent request failures should raise
`AgentPermanentError`, which activities convert to a non-retryable Temporal
application error.
