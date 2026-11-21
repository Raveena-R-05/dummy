"""Supplier flow: dashboard, assign a car, see offers/bookings, decide change requests."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import Booking, ChangeRequest, Offer, RideRequest
from schemas.booking import ChangeDecision
from schemas.offer import AssignOffer
from services import booking as booking_service
from services import matching
from services.catalog import catalog
from services.errors import not_found
from services.presenters import (booking_view, change_view, offer_view, request_view)

router = APIRouter(prefix="/suppliers", tags=["supplier"])


def _company(company_id: str) -> dict:
    company = catalog().companies.get(company_id)
    if company is None:
        raise not_found(f"Supplier '{company_id}'")
    return company


@router.get("")
def list_suppliers():
    """For the 'choose who you are' screen."""
    return [
        {"company_id": c["company_id"], "name": c["name"], "rating": c["rating"],
         "airports": c["airports"], "service_from": c["service_from"],
         "service_until": c["service_until"], "vehicle_count": len(c["vehicles"])}
        for c in catalog().companies.values()
    ]


@router.get("/{company_id}")
def get_supplier(company_id: str):
    return _company(company_id)


@router.get("/{company_id}/requests")
def dashboard(company_id: str, db: Session = Depends(get_db)):
    """M2 / R4: only the OPEN requests this supplier can serve, with all details."""
    company = _company(company_id)
    result = []
    for req in db.scalars(select(RideRequest).where(RideRequest.status == "OPEN")
                          .order_by(RideRequest.pickup)):
        need = matching.need_from_request(req)
        verdict = matching.evaluate_company(db, company, need)
        if not verdict["eligible"]:
            continue
        view = request_view(db, req, with_matching=False)
        view["eligible_vehicle_ids"] = verdict["eligible_vehicle_ids"]
        view["my_offers"] = [offer_view(db, o) for o in req.offers if o.company_id == company_id]
        result.append(view)
    return result


@router.get("/{company_id}/requests/{request_id}")
def request_detail(company_id: str, request_id: str, db: Session = Depends(get_db)):
    """One request with all details, plus every car of this supplier and why it
    fits or not (R4, R5, R6). The supplier can pick any car; the backend refuses bad ones."""
    company = _company(company_id)
    req = db.get(RideRequest, request_id)
    if req is None:
        raise not_found(f"Request '{request_id}'")
    verdict = matching.evaluate_company(db, company, matching.need_from_request(req))
    return {
        "request": request_view(db, req, with_matching=False),
        "supplier_can_serve": verdict["eligible"],
        "supplier_violations": verdict["company_violations"],
        "vehicles": verdict["vehicles"],
        "my_offers": [offer_view(db, o) for o in req.offers if o.company_id == company_id],
    }


@router.post("/{company_id}/requests/{request_id}/offers", status_code=201)
def assign_car(company_id: str, request_id: str, body: AssignOffer, db: Session = Depends(get_db)):
    """M3 / R7: assign a car with a price. Refused (422) with the broken rule
    (R3, R4, R5 or R6) in `detail.rule` and `detail.message`.
    Call it again with another car to assign several cars (G1)."""
    offer = booking_service.assign_offer(
        db, company_id, request_id, body.vehicle_id, body.price_inr,
        body.expires_at, body.expires_in_minutes)
    return offer_view(db, offer)


@router.get("/{company_id}/offers")
def my_offers(company_id: str, db: Session = Depends(get_db)):
    """All taxis this supplier assigned, with their status (open / booked / rejected / not chosen)."""
    _company(company_id)
    offers = db.scalars(select(Offer).where(Offer.company_id == company_id).order_by(Offer.id.desc()))
    result = []
    for o in offers:
        view = offer_view(db, o)
        view["request"] = request_view(db, o.request, with_matching=False)
        result.append(view)
    return result


@router.get("/{company_id}/bookings")
def my_bookings(company_id: str, db: Session = Depends(get_db)):
    _company(company_id)
    bookings = db.scalars(select(Booking).where(Booking.company_id == company_id)
                          .order_by(Booking.id.desc()))
    return [booking_view(b) for b in bookings]


@router.get("/{company_id}/change-requests")
def my_change_requests(company_id: str, status: str = "WAITING", db: Session = Depends(get_db)):
    """Change requests for this supplier's bookings (default: the ones waiting for an answer)."""
    _company(company_id)
    query = (select(ChangeRequest).join(Booking).where(Booking.company_id == company_id)
             .order_by(ChangeRequest.id.desc()))
    if status.upper() != "ALL":
        query = query.where(ChangeRequest.status == status.upper())
    result = []
    for c in db.scalars(query):
        view = change_view(c)
        view["booking"] = booking_view(c.booking)
        result.append(view)
    return result


@router.post("/{company_id}/change-requests/{change_id}/accept")
def accept_change(company_id: str, change_id: int, db: Session = Depends(get_db)):
    """R9: accepted only if the new pickup follows R2 and the same car is free then.
    Otherwise 409 with the reason; the request stays WAITING so the supplier can reject it."""
    _company(company_id)
    change = booking_service.accept_change(db, company_id, change_id)
    return {**change_view(change), "booking": booking_view(change.booking)}


@router.post("/{company_id}/change-requests/{change_id}/reject")
def reject_change(company_id: str, change_id: int, body: ChangeDecision = ChangeDecision(),
                  db: Session = Depends(get_db)):
    """The old booking stays as it was."""
    _company(company_id)
    change = booking_service.reject_change(db, company_id, change_id, body.reason)
    return {**change_view(change), "booking": booking_view(change.booking)}
