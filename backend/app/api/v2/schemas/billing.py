from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class BillingOverview(BaseModel):
    plan_name: str
    plan_display_name: str
    subscription_status: str          # 'active' | 'cancelled' | 'none'
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    cancel_at_period_end: bool = False
    intake_total: int = 0             # -1 = unlimited
    intake_used: int = 0
    intake_topup: int = 0
    interview_total: int = 0          # -1 = unlimited
    interview_used: int = 0
    interview_topup: int = 0
