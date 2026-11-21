"""Turn database rows into the JSON the frontend receives."""
from sqlalchemy.orm import Session

from models import Booking, ChangeRequest, Offer, RideRequest
from services import availability, matching
from services.booking import offer_status
from services.catalog import catalog, earliest_pickup


def flight_view(flight: dict) -> dict:
    return {
        "flight_id": flight["flight_id"], "airline": flight["airline"],
        "flight_number": flight["flight_number"], "from": flight["from"], "to": flight["to"],
        "departure_local": flight["departure_local"], "arrival_local": flight["arrival_local"],
        "earliest_pickup": earliest_pickup(flight),
    }


def hotel_view(hotel: dict) -> dict:
    return {k: hotel[k] for k in ("hotel_id", "name", "city", "area", "stars", "rating")}


def company_brief(company_id: str) -> dict:
    c = catalog().companies[company_id]
    return {"company_id": c["company_id"], "name": c["name"], "rating": c["rating"]}


def vehicle_view(vehicle_id: str) -> dict:
    _, v = catalog().vehicles[vehicle_id]
    return {k: v[k] for k in ("vehicle_id", "type", "seats", "large_bags", "small_bags")}


def request_view(db: Session, req: RideRequest, with_matching: bool = True) -> dict:
    need = matching.need_from_request(req)
    t = need.trip
    view = {
        "id": req.id, "status": req.status, "traveler_name": req.traveler_name,
        "flight": flight_view(t.flight), "hotel": hotel_view(t.hotel),
        "adults": req.adults, "child_ages": req.child_ages, "passengers": need.passengers,
        "large_bags": req.large_bags, "small_bags": req.small_bags,
        "car_type": req.car_type, "pickup": req.pickup,
        "busy_start": t.busy_start, "busy_end": t.busy_end,
        "price_inr": req.price_inr,
        "price_range": {"min": t.route["price_min_inr"], "max": t.route["price_max_inr"]},
        "route": {"airport": t.airport, "distance_km": t.route["distance_km"],
                  "drive_minutes": t.route["drive_minutes"]},
        "offer_count": len(req.offers), "created_at": req.created_at,
    }
    if with_matching:
        if req.status == "OPEN":
            evaluations = matching.evaluate_all(db, need)
            serving = [e for e in evaluations if e["eligible"]]
            view["can_be_served"] = bool(serving)
            view["serving_suppliers"] = [{"company_id": e["company_id"], "name": e["name"]}
                                         for e in serving]
            view["no_supplier_reason"] = (
                None if serving else matching.explain_unserved(evaluations, need))
        else:
            view["can_be_served"], view["serving_suppliers"], view["no_supplier_reason"] = None, [], None
    return view


def offer_view(db: Session, offer: Offer) -> dict:
    status = offer_status(offer)
    car_free, can_book = None, False
    if status == "OPEN":
        t = matching.need_from_request(offer.request).trip
        car_free = availability.vehicle_conflict(
            db, offer.vehicle_id, t.busy_start, t.busy_end) is None
        can_book = car_free and offer.request.status == "OPEN"
    return {
        "id": offer.id, "request_id": offer.request_id, "status": status,
        "supplier": company_brief(offer.company_id), "car": vehicle_view(offer.vehicle_id),
        "price_inr": offer.price_inr, "expires_at": offer.expires_at,
        "car_free": car_free, "can_book": can_book, "created_at": offer.created_at,
    }


def change_view(change: ChangeRequest) -> dict:
    flight = catalog().flights.get(change.new_flight_id) if change.new_flight_id else None
    return {
        "id": change.id, "booking_id": change.booking_id, "status": change.status,
        "new_flight": flight_view(flight) if flight else None,
        "new_pickup": change.new_pickup, "reason": change.reason,
        "created_at": change.created_at, "decided_at": change.decided_at,
    }


def booking_view(booking: Booking) -> dict:
    req = booking.request
    cat = catalog()
    return {
        "booking_number": booking.booking_number, "status": booking.status,
        "traveler_name": req.traveler_name, "request_id": req.id,
        "flight": flight_view(cat.flights[booking.flight_id]),
        "hotel": hotel_view(cat.hotels[req.hotel_id]),
        "pickup": booking.pickup,
        "busy_start": booking.busy_start, "busy_end": booking.busy_end,
        "supplier": company_brief(booking.company_id), "car": vehicle_view(booking.vehicle_id),
        "price_inr": booking.price_inr,
        "passengers": req.adults + len(req.child_ages or []),
        "adults": req.adults, "child_ages": req.child_ages,
        "large_bags": req.large_bags, "small_bags": req.small_bags,
        "created_at": booking.created_at,
        "change_requests": [change_view(c) for c in booking.change_requests],
        "pending_change": any(c.status == "WAITING" for c in booking.change_requests),
    }
