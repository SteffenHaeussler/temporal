from ticketflow.models import (
    ActionType,
    ProposedAction,
    TicketResult,
    TicketStatus,
)


def test_ticket_result_defaults_to_no_refund():
    result = TicketResult(
        ticket_id="t1", status=TicketStatus.RESOLVED, reply_text="done"
    )
    assert result.refund_executed is False


def test_reply_only_action_has_no_refund_amount():
    action = ProposedAction(type=ActionType.REPLY_ONLY)
    assert action.refund_amount is None
