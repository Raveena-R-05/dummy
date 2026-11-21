"""Traveler: booking summary (M5) and change requests (M7)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from schemas.booking import ChangeRequestCreate
from services import booking as booking_service
from services.presenters import booking_view, change_view

router = APIRouter(prefix="/bookings", tags=["traveler"])


@router.get("/{booking_number}")
def get_booking(booking_number: str, db: Session = Depends(get_db)):
    """Summary: flight, hotel, pickup, supplier, car, price, change requests.
    A wrong number gives 404 'not found'."""
    return booking_view(booking_service.get_booking(db, booking_number))


@router.post("/{booking_number}/change-requests", status_code=201)
def create_change_request(booking_number: str, body: ChangeRequestCreate,
                          db: Session = Depends(get_db)):
    change = booking_service.create_change_request(
        db, booking_number, body.new_flight_id, body.new_pickup)
    return change_view(change)
