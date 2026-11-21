"""Offers, bookings and change requests (R7, R8, R9, M3, M4, M6, M7, G4)."""
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Booking, ChangeRequest, Offer, RideRequest
from services import availability, matching, pricing
from services.catalog import catalog
from services.errors import RuleError, not_found, raise_violations, violation


def now() -> datetime:
    return datetime.now()


def offer_status(offer: Offer) -> str:
    """Stored status, except an OPEN offer whose end time has passed is EXPIRED (G4)."""
    if offer.status == "OPEN" and offer.expires_at and offer.expires_at <= now():
        return "EXPIRED"
    return offer.status


# ----------------------------------------------------------------------------
# M3 / R7: supplier assigns a car with a price
# ----------------------------------------------------------------------------
def assign_offer(db: Session, company_id: str, request_id: str, vehicle_id: str, price: int,
                 expires_at: Optional[datetime], expires_in_minutes: Optional[int]) -> Offer:
    company = catalog().companies.get(company_id)
    if company is None:
        raise not_found(f"Supplier '{company_id}'")
    req = db.get(RideRequest, request_id)
    if req is None:
        raise not_found(f"Request '{request_id}'")
    if req.status != "OPEN":
        raise RuleError("REQUEST_CLOSED", f"Request {request_id} is already booked.", 409)

    need = matching.need_from_request(req)
    raise_violations(matching.assignment_violations(db, company, vehicle_id, price, need))

    if expires_in_minutes:
        expires_at = now() + timedelta(minutes=expires_in_minutes)
    if expires_at is not None:
        expires_at = expires_at.replace(tzinfo=None)
        if expires_at <= now():
            raise RuleError("G4", "The end time of the taxi must be in the future.")

    duplicate = db.scalar(select(Offer.id).where(
        Offer.request_id == request_id, Offer.vehicle_id == vehicle_id, Offer.status == "OPEN"))
    if duplicate:
        raise RuleError("DUPLICATE", f"Car {vehicle_id} is already assigned to this request.", 409)

    offer = Offer(request_id=request_id, company_id=company_id, vehicle_id=vehicle_id,
                  price_inr=price, status="OPEN", expires_at=expires_at)
    db.add(offer)
    db.commit()
    return offer


# ----------------------------------------------------------------------------
# M4 / R8 / M6: traveler books or rejects a taxi
# ----------------------------------------------------------------------------
def _new_booking_number(db: Session) -> str:
    while True:  # 10 digits, never starts with 0
        number = str(secrets.randbelow(9_000_000_000) + 1_000_000_000)
        if not db.scalar(select(Booking.id).where(Booking.booking_number == number)):
            return number


def book_offer(db: Session, offer_id: int) -> Booking:
    offer = db.get(Offer, offer_id)
    if offer is None:
        raise not_found(f"Taxi offer {offer_id}")
    req = offer.request

    status = offer_status(offer)
    if status == "REJECTED":
        raise RuleError("R8", "You rejected this taxi, so it cannot be booked.", 409)
    if status == "NOT_CHOSEN":
        raise RuleError("R8", "You booked another taxi for this request; this one was not chosen.", 409)
    if status == "BOOKED":
        raise RuleError("R8", "This taxi is already booked.", 409)
    if status == "EXPIRED":
        raise RuleError("G4", f"This taxi offer ended at {offer.expires_at:%d %b %Y, %H:%M}.", 409)
    if req.status != "OPEN":
        raise RuleError("R8", "This request already has a booking.", 409)

    # M6: the car must have no overlapping busy time at the moment of booking
    need = matching.need_from_request(req)
    t = need.trip
    conflict = availability.vehicle_conflict(db, offer.vehicle_id, t.busy_start, t.busy_end)
    if conflict:
        raise RuleError(
            "R6",
            f"Car {offer.vehicle_id} is no longer free: it is busy "
            f"{matching.fmt(conflict['start'])} to {matching.fmt(conflict['end'])}, "
            "which overlaps your ride. Please choose another taxi.",
            409, conflict=conflict,
        )

    booking = Booking(
        booking_number=_new_booking_number(db),
        offer_id=offer.id, request_id=req.id,
        company_id=offer.company_id, vehicle_id=offer.vehicle_id,
        flight_id=req.flight_id, pickup=t.pickup,
        busy_start=t.busy_start, busy_end=t.busy_end,
        price_inr=offer.price_inr, status="CONFIRMED",
    )
    offer.status = "BOOKED"
    for other in req.offers:
        if other.id != offer.id and other.status == "OPEN":
            other.status = "NOT_CHOSEN"
    req.status = "BOOKED"
    db.add(booking)
    db.commit()
    return booking


def reject_offer(db: Session, offer_id: int) -> Offer:
    offer = db.get(Offer, offer_id)
    if offer is None:
        raise not_found(f"Taxi offer {offer_id}")
    if offer.status == "BOOKED":
        raise RuleError("R8", "A booked taxi cannot be rejected.", 409)
    if offer.status == "NOT_CHOSEN":
        raise RuleError("R8", "This taxi was not chosen; there is nothing to reject.", 409)
    offer.status = "REJECTED"
    db.commit()
    return offer


def get_booking(db: Session, number: str) -> Booking:
    booking = None
    if re.fullmatch(r"\d{10}", number or ""):
        booking = db.scalar(select(Booking).where(Booking.booking_number == number))
    if booking is None:
        raise not_found(f"Booking '{number}'")
    return booking


# ----------------------------------------------------------------------------
# M7 / R9: change requests
# ----------------------------------------------------------------------------
def _change_violations(db: Session, booking: Booking, trip: matching.Trip,
                       check_car_free: bool) -> list[dict]:
    """What would break if this booking moved to `trip` (same supplier, same car, same price)."""
    company = catalog().companies[booking.company_id]
    found = matching.company_level_violations(company, trip.airport, trip.city, trip.area, trip.pickup)
    price_problem = pricing.price_violation(booking.price_inr, trip.route, "The booked price")
    if price_problem:
        found.append(price_problem)
    if check_car_free:
        conflict = availability.vehicle_conflict(
            db, booking.vehicle_id, trip.busy_start, trip.busy_end, exclude_booking_id=booking.id)
        if conflict:
            found.append(violation(
                "R6", "BUSY",
                f"Car {booking.vehicle_id} is busy {matching.fmt(conflict['start'])} to "
                f"{matching.fmt(conflict['end'])}, which overlaps the new ride "
                f"({matching.fmt(trip.busy_start)} to {matching.fmt(trip.busy_end)}).",
                conflict=conflict))
    return found


def create_change_request(db: Session, number: str, new_flight_id: Optional[str],
                          new_pickup: Optional[datetime]) -> ChangeRequest:
    booking = get_booking(db, number)
    if new_flight_id is None and new_pickup is None:
        raise RuleError("INVALID_VALUE", "Send a new flight, a new pickup time, or both.")
    if any(c.status == "WAITING" for c in booking.change_requests):
        raise RuleError("CHANGE_PENDING",
                        "This booking already has a change request waiting for the supplier.", 409)

    flight_id = new_flight_id or booking.flight_id
    # R1 + R2 for the new flight / pickup. New flight without a pickup -> landing + 60 min.
    trip = matching.resolve_trip(flight_id, booking.request.hotel_id, new_pickup)
    if flight_id == booking.flight_id and trip.pickup == booking.pickup:
        raise RuleError("INVALID_VALUE", "The new flight and pickup are the same as the booking.")

    # Things that can never work are refused now. Whether the car is free is the
    # supplier's decision, and is re-checked when it accepts.
    raise_violations(_change_violations(db, booking, trip, check_car_free=False))

    change = ChangeRequest(booking_id=booking.id, new_flight_id=new_flight_id,
                           new_pickup=trip.pickup, status="WAITING")
    db.add(change)
    db.commit()
    return change


def _get_change_for_company(db: Session, company_id: str, change_id: int) -> ChangeRequest:
    change = db.get(ChangeRequest, change_id)
    if change is None or change.booking.company_id != company_id:
        raise not_found(f"Change request {change_id}")
    if change.status != "WAITING":
        raise RuleError("CHANGE_DECIDED", f"This change request is already {change.status}.", 409)
    return change


def accept_change(db: Session, company_id: str, change_id: int) -> ChangeRequest:
    change = _get_change_for_company(db, company_id, change_id)
    booking = change.booking
    flight_id = change.new_flight_id or booking.flight_id

    trip = matching.resolve_trip(flight_id, booking.request.hotel_id, change.new_pickup)  # R2
    raise_violations(_change_violations(db, booking, trip, check_car_free=True), 409)      # R6 etc.

    booking.flight_id = flight_id
    booking.pickup = trip.pickup
    booking.busy_start, booking.busy_end = trip.busy_start, trip.busy_end
    change.status, change.decided_at = "ACCEPTED", now()
    db.commit()
    return change


def reject_change(db: Session, company_id: str, change_id: int, reason: Optional[str]) -> ChangeRequest:
    change = _get_change_for_company(db, company_id, change_id)
    change.status, change.reason, change.decided_at = "REJECTED", reason, now()
    db.commit()  # the old booking is untouched
    return change
