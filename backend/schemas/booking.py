from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ChangeRequestCreate(BaseModel):
    """Body of POST /bookings/{number}/change-requests (M7). Send a flight, a pickup, or both."""

    new_flight_id: Optional[str] = None
    new_pickup: Optional[datetime] = None


class ChangeDecision(BaseModel):
    reason: Optional[str] = None
