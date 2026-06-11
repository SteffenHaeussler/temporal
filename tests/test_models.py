import pytest
from pydantic import ValidationError

from ticketflow.models import (
    ActionType,
    Classification,
    DraftReply,
    ProposedAction,
    TicketCategory,
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


def test_classification_confidence_must_be_between_zero_and_one():
    with pytest.raises(ValidationError):
        Classification(category=TicketCategory.BILLING, confidence=-0.1)

    with pytest.raises(ValidationError):
        Classification(category=TicketCategory.BILLING, confidence=1.1)


def test_draft_reply_confidence_must_not_exceed_one():
    with pytest.raises(ValidationError):
        DraftReply(
            reply_text="No problem.",
            action=ProposedAction(type=ActionType.REPLY_ONLY),
            confidence=1.1,
        )


def test_refund_action_requires_positive_refund_amount():
    with pytest.raises(ValidationError):
        ProposedAction(type=ActionType.REFUND)

    with pytest.raises(ValidationError):
        ProposedAction(type=ActionType.REFUND, refund_amount=0)

    action = ProposedAction(type=ActionType.REFUND, refund_amount=1.0)
    assert action.refund_amount == 1.0
