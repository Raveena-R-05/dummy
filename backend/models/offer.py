from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Offer(Base):
    """A taxi a supplier assigned to a request.

    status: OPEN | BOOKED | REJECTED | NOT_CHOSEN
    (EXPIRED is not stored: it is derived from `expires_at`, see services/booking.py)
    """

    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("ride_requests.id"), index=True)
    company_id: Mapped[str] = mapped_column(String(20), index=True)
    vehicle_id: Mapped[str] = mapped_column(String(20), index=True)
    price_inr: Mapped[int]
    status: Mapped[str] = mapped_column(String(12), default="OPEN", index=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # G4
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    request: Mapped["RideRequest"] = relationship(back_populates="offers")  # noqa: F821
    booking: Mapped[Optional["Booking"]] = relationship(  # noqa: F821
        back_populates="offer", uselist=False
    )
