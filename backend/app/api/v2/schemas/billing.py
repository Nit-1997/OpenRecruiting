from pydantic import BaseModel


class BillingOverview(BaseModel):
    """The org's credit budget. There are no plans or subscriptions — the
    organization is the budget holder and every member draws from this one
    pool. `total = -1` means unlimited.
    """
    intake_total: int = 0
    intake_used: int = 0
    intake_topup: int = 0
    interview_total: int = 0
    interview_used: int = 0
    interview_topup: int = 0
