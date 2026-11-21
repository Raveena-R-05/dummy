from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

CarType = Literal["HATCHBACK", "SEDAN", "SUV", "BUS"]


class RideRequestCreate(BaseModel):
    """Body of POST /requests (M1). Business rules R1-R3 are checked in the service,
    so the messages are clear; Pydantic only checks types here."""

    traveler_name: str = Field(..., description="Name shown to suppliers")
    flight_id: str
    hotel_id: str
    adults: int
    child_ages: List[int] = Field(default_factory=list)
    large_bags: int = 0
    small_bags: int = 0
    pickup: Optional[datetime] = Field(
        None, description="Local time at the airport. Empty = landing + 60 minutes"
    )
    car_type: Optional[CarType] = Field(None, description="Empty = any type (G2)")
    price_inr: int

    @field_validator("car_type", mode="before")
    @classmethod
    def _upper(cls, v):
        if isinstance(v, str):
            v = v.strip().upper()
            return v or None
        return v
