from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Booking(Base):
    """A confirmed booking. It keeps the car busy from busy_start to busy_end (R6).

    flight_id / pickup / busy_* always hold the CURRENT ride: they are updated
    when a supplier accepts a change request.
    """

    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    booking_number: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"), unique=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("ride_requests.id"), index=True)
    company_id: Mapped[str] = mapped_column(String(20), index=True)
    vehicle_id: Mapped[str] = mapped_column(String(20), index=True)
    flight_id: Mapped[str] = mapped_column(String(20))
    pickup: Mapped[datetime] = mapped_column(DateTime)
    busy_start: Mapped[datetime] = mapped_column(DateTime)
    busy_end: Mapped[datetime] = mapped_column(DateTime)
    price_inr: Mapped[int]
    status: Mapped[str] = mapped_column(String(12), default="CONFIRMED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    offer: Mapped["Offer"] = relationship(back_populates="booking")  # noqa: F821
    request: Mapped["RideRequest"] = relationship(back_populates="bookings")  # noqa: F821
    change_requests: Mapped[list["ChangeRequest"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan", order_by="ChangeRequest.id"
    )


class ChangeRequest(Base):
    """Traveler asks for a new flight and/or pickup. status: WAITING | ACCEPTED | REJECTED"""

    __tablename__ = "change_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), index=True)
    new_flight_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    new_pickup: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(10), default="WAITING", index=True)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    booking: Mapped["Booking"] = relationship(back_populates="change_requests")
