"""Data models shared by API, workflow, and activities."""

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class TicketCategory(StrEnum):
    BILLING = "billing"
    TECHNICAL = "technical"
    ACCOUNT = "account"
    GENERAL = "general"


class ActionType(StrEnum):
    REPLY_ONLY = "reply_only"
    REFUND = "refund"


class TicketStatus(StrEnum):
    RECEIVED = "received"
    CLASSIFYING = "classifying"
    DRAFTING = "drafting"
    AWAITING_APPROVAL = "awaiting_approval"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    ESCALATED = "escalated"


class Ticket(BaseModel):
    id: str
    customer_email: str
    subject: str
    body: str


class Classification(BaseModel):
    category: TicketCategory
    confidence: float = Field(ge=0.0, le=1.0)


class ProposedAction(BaseModel):
    type: ActionType
    refund_amount: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def require_refund_amount_for_refunds(self) -> "ProposedAction":
        if self.type == ActionType.REFUND and self.refund_amount is None:
            raise ValueError("refund_amount is required for refund actions")
        return self


class DraftReply(BaseModel):
    reply_text: str
    action: ProposedAction
    confidence: float = Field(ge=0.0, le=1.0)


class ApprovalDecision(BaseModel):
    approved: bool
    note: str | None = None


class TicketResult(BaseModel):
    ticket_id: str
    status: TicketStatus
    reply_text: str
    refund_executed: bool = False


class TicketStatusInfo(BaseModel):
    ticket_id: str
    status: TicketStatus
    classification: Classification | None = None
    draft: DraftReply | None = None
    decision: ApprovalDecision | None = None
