"""Traveler: post a request, see it, see the taxis assigned to it."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import RideRequest
from schemas.ride_request import RideRequestCreate
from services import matching, ride_requests
from services.errors import not_found
from services.presenters import offer_view, request_view

router = APIRouter(prefix="/requests", tags=["traveler"])


@router.post("", status_code=201)
def create_request(body: RideRequestCreate, db: Session = Depends(get_db)):
    """M1. Refuses R1 / R2 / R3 with a clear message. If the request is saved but no
    supplier can serve it, `can_be_served` is false and `no_supplier_reason` says why (M2)."""
    req = ride_requests.create_request(db, body)
    return request_view(db, req)


@router.get("")
def list_requests(traveler_name: Optional[str] = None, status: Optional[str] = None,
                  db: Session = Depends(get_db)):
    query = select(RideRequest).order_by(RideRequest.created_at.desc(), RideRequest.id.desc())
    if traveler_name:
        query = query.where(RideRequest.traveler_name.ilike(f"%{traveler_name}%"))
    if status:
        query = query.where(RideRequest.status == status.upper())
    return [request_view(db, r) for r in db.scalars(query)]


@router.get("/{request_id}")
def get_request(request_id: str, db: Session = Depends(get_db)):
    req = db.get(RideRequest, request_id)
    if req is None:
        raise not_found(f"Request '{request_id}'")
    return request_view(db, req)


@router.get("/{request_id}/offers")
def request_offers(
    request_id: str,
    sort: str = Query("price_asc", pattern="^(price_asc|price_desc|rating)$"),
    car_type: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """M4 + G5: every taxi assigned to the request. Sort by price/rating, filter by car type."""
    req = db.get(RideRequest, request_id)
    if req is None:
        raise not_found(f"Request '{request_id}'")
    offers = [offer_view(db, o) for o in req.offers]
    if car_type:
        offers = [o for o in offers if o["car"]["type"] == car_type.upper()]
    if status:
        offers = [o for o in offers if o["status"] == status.upper()]
    if sort == "price_desc":
        offers.sort(key=lambda o: -o["price_inr"])
    elif sort == "rating":
        offers.sort(key=lambda o: (-o["supplier"]["rating"], o["price_inr"]))
    else:
        offers.sort(key=lambda o: o["price_inr"])
    return offers
