from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AssignOffer(BaseModel):
    """Body of POST /suppliers/{company_id}/requests/{request_id}/offers (M3)."""

    vehicle_id: str
    price_inr: int
    expires_at: Optional[datetime] = Field(None, description="G4: taxi ends at this time")
    expires_in_minutes: Optional[int] = Field(None, gt=0, description="G4: shortcut for expires_at")
