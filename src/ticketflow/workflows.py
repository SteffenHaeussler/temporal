"""Durable per-ticket workflow with conditional human approval."""

import asyncio
from datetime import timedelta
from typing import cast

from temporalio import workflow
from temporalio.common import RetryPolicy, SearchAttributeKey
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from ticketflow.activities import TicketActivities
    from ticketflow.models import (
        ActionType,
        ApprovalDecision,
        Classification,
        DraftReply,
        Ticket,
        TicketResult,
        TicketStatus,
        TicketStatusInfo,
    )

CONFIDENCE_THRESHOLD = 0.75
APPROVAL_TIMEOUT = timedelta(hours=24)
ACTIVITY_TIMEOUT = timedelta(seconds=30)
RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_attempts=5,
)

REJECTION_REPLY = (
    "Thanks for your patience. After review we cannot fulfil this request "
    "automatically; a human agent will follow up shortly."
)
ESCALATION_REPLY = (
    "We need a bit more time with your request and have escalated your "
    "ticket to a human agent."
)
TICKET_STATUS_ATTR = SearchAttributeKey.for_keyword("TicketStatus")


@workflow.defn
class TicketWorkflow:
    def __init__(self) -> None:
        self._ticket: Ticket | None = None
        self._status = TicketStatus.RECEIVED
        self._classification: Classification | None = None
        self._draft: DraftReply | None = None
        self._decision: ApprovalDecision | None = None

    @workflow.run
    async def run(self, ticket: Ticket) -> TicketResult:
        self._ticket = ticket
        self._set_status(TicketStatus.RECEIVED)

        self._set_status(TicketStatus.CLASSIFYING)
        try:
            self._classification = await workflow.execute_activity_method(
                TicketActivities.classify_ticket,
                ticket,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RETRY_POLICY,
            )
        except ActivityError:
            return await self._finish(
                reply_text=ESCALATION_REPLY,
                refund=False,
                status=TicketStatus.ESCALATED,
            )

        self._set_status(TicketStatus.DRAFTING)
        try:
            self._draft = await workflow.execute_activity_method(
                TicketActivities.draft_reply,
                args=[ticket, self._classification],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RETRY_POLICY,
            )
        except ActivityError:
            return await self._finish(
                reply_text=ESCALATION_REPLY,
                refund=False,
                status=TicketStatus.ESCALATED,
            )

        needs_approval = (
            self._draft.action.type == ActionType.REFUND
            or self._draft.confidence < CONFIDENCE_THRESHOLD
        )
        if not needs_approval:
            return await self._finish(
                reply_text=self._draft.reply_text,
                refund=False,
                status=TicketStatus.RESOLVED,
            )

        self._set_status(TicketStatus.AWAITING_APPROVAL)
        try:
            await workflow.wait_condition(
                lambda: self._decision is not None, timeout=APPROVAL_TIMEOUT
            )
        except asyncio.TimeoutError:
            return await self._finish(
                reply_text=ESCALATION_REPLY,
                refund=False,
                status=TicketStatus.ESCALATED,
            )

        if not self._decision.approved:
            return await self._finish(
                reply_text=REJECTION_REPLY,
                refund=False,
                status=TicketStatus.REJECTED,
            )

        return await self._finish(
            reply_text=self._draft.reply_text,
            refund=self._draft.action.type == ActionType.REFUND,
            status=TicketStatus.RESOLVED,
        )

    @workflow.update
    async def submit_approval(self, decision: ApprovalDecision) -> TicketStatus:
        self._decision = decision
        await workflow.wait_condition(
            lambda: self._status != TicketStatus.AWAITING_APPROVAL
        )
        return self._status

    @submit_approval.validator
    def validate_submit_approval(self, _decision: ApprovalDecision) -> None:
        if self._status != TicketStatus.AWAITING_APPROVAL or self._decision is not None:
            raise ApplicationError(
                "ticket is not awaiting approval", non_retryable=True
            )

    @workflow.query
    def status(self) -> TicketStatusInfo:
        return TicketStatusInfo(
            ticket_id=self._ticket.id if self._ticket else "",
            status=self._status,
            classification=self._classification,
            draft=self._draft,
            decision=self._decision,
        )

    async def _finish(
        self, *, reply_text: str, refund: bool, status: TicketStatus
    ) -> TicketResult:
        if self._ticket is None:
            raise ApplicationError("workflow has no ticket", non_retryable=True)
        if refund:
            draft = cast(DraftReply, self._draft)
            await workflow.execute_activity_method(
                TicketActivities.execute_refund,
                args=[self._ticket.id, draft.action.refund_amount],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RETRY_POLICY,
            )
        await workflow.execute_activity_method(
            TicketActivities.send_reply,
            args=[self._ticket, reply_text],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        self._set_status(status)
        return TicketResult(
            ticket_id=self._ticket.id,
            status=status,
            reply_text=reply_text,
            refund_executed=refund,
        )

    def _set_status(self, status: TicketStatus) -> None:
        self._status = status
        workflow.upsert_search_attributes([TICKET_STATUS_ATTR.value_set(status.value)])
