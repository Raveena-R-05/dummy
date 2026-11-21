"""R6 (car is free) and the opening-hours part of R4."""
from datetime import datetime, time
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Booking
from services.catalog import catalog


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Two busy times overlap if one starts before the other ends.
    11:00-14:00 and 14:00-16:00 do NOT overlap."""
    return a_start < b_end and b_start < a_end


def vehicle_conflict(
    db: Session,
    vehicle_id: str,
    start: datetime,
    end: datetime,
    exclude_booking_id: Optional[int] = None,
) -> Optional[dict]:
    """Return the first busy time of the car that overlaps [start, end), or None if free.

    A car is busy because of (1) rides in booked_rides.json and
    (2) confirmed bookings made in this app.
    """
    for b_start, b_end, ride_id in catalog().fixed_busy.get(vehicle_id, []):
        if overlaps(start, end, b_start, b_end):
            return {"source": "booked_rides.json", "ref": ride_id, "start": b_start, "end": b_end}

    query = select(Booking).where(Booking.vehicle_id == vehicle_id, Booking.status == "CONFIRMED")
    if exclude_booking_id is not None:
        query = query.where(Booking.id != exclude_booking_id)
    for booking in db.scalars(query):
        if overlaps(start, end, booking.busy_start, booking.busy_end):
            return {
                "source": "booking",
                "ref": booking.booking_number,
                "start": booking.busy_start,
                "end": booking.busy_end,
            }
    return None


def is_open(service_from: str, service_until: str, at: time) -> bool:
    """Opening hours, both ends included. '05:00'-'01:00' runs past midnight."""
    start = time.fromisoformat(service_from)
    end = time.fromisoformat(service_until)
    at = at.replace(second=0, microsecond=0)
    if start <= end:
        return start <= at <= end
    return at >= start or at <= end
