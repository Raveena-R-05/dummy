"""Traveler: book or reject one taxi (M4, R8)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import Offer
from services import booking as booking_service
from services.errors import not_found
from services.presenters import booking_view, offer_view

router = APIRouter(prefix="/offers", tags=["traveler"])


@router.get("/{offer_id}")
def get_offer(offer_id: int, db: Session = Depends(get_db)):
    offer = db.get(Offer, offer_id)
    if offer is None:
        raise not_found(f"Taxi offer {offer_id}")
    return offer_view(db, offer)


@router.post("/{offer_id}/book", status_code=201)
def book(offer_id: int, db: Session = Depends(get_db)):
    """Books the taxi: 10-digit booking number, other taxis become NOT_CHOSEN,
    the car is busy. Refused (409) if the car became busy (M6)."""
    return booking_view(booking_service.book_offer(db, offer_id))


@router.post("/{offer_id}/reject")
def reject(offer_id: int, db: Session = Depends(get_db)):
    return offer_view(db, booking_service.reject_offer(db, offer_id))
