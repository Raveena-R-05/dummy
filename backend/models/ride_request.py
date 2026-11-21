from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class RideRequest(Base):
    """A traveler's ride request. status: OPEN -> BOOKED."""

    __tablename__ = "ride_requests"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # REQ-0004 ...
    traveler_name: Mapped[str] = mapped_column(String(120))
    flight_id: Mapped[str] = mapped_column(String(20))
    hotel_id: Mapped[str] = mapped_column(String(20))
    adults: Mapped[int]
    child_ages: Mapped[list] = mapped_column(JSON, default=list)
    large_bags: Mapped[int]
    small_bags: Mapped[int]
    pickup: Mapped[datetime] = mapped_column(DateTime)  # local time of the airport
    car_type: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    price_inr: Mapped[int]
    status: Mapped[str] = mapped_column(String(12), default="OPEN", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    offers: Mapped[list["Offer"]] = relationship(  # noqa: F821
        back_populates="request", cascade="all, delete-orphan", order_by="Offer.id"
    )
    bookings: Mapped[list["Booking"]] = relationship(back_populates="request")  # noqa: F821
