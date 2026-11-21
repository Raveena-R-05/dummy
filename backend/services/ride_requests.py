"""Create ride requests (M1) and load the open requests of the data pack."""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import RideRequest
from schemas.ride_request import RideRequestCreate
from services import matching, pricing
from services.catalog import catalog, parse_dt


def next_request_id(db: Session) -> str:
    numbers = [
        int(m.group(1))
        for rid in db.scalars(select(RideRequest.id))
        if (m := re.fullmatch(r"REQ-(\d+)", rid))
    ]
    return f"REQ-{(max(numbers) if numbers else 0) + 1:04d}"


def create_request(db: Session, body: RideRequestCreate) -> RideRequest:
    # R1: people, flight, hotel, airport serves the hotel's city
    matching.validate_party(body.traveler_name, body.adults, body.child_ages,
                            body.large_bags, body.small_bags)
    # R1 + R2: resolve the trip (pickup defaults to landing + 60 min)
    trip = matching.resolve_trip(body.flight_id, body.hotel_id, body.pickup)
    # R3: the traveler's price is inside the route's range
    pricing.check_price(body.price_inr, trip.route, "Your price")

    req = RideRequest(
        id=next_request_id(db),
        traveler_name=body.traveler_name.strip(),
        flight_id=body.flight_id,
        hotel_id=body.hotel_id,
        adults=body.adults,
        child_ages=list(body.child_ages),
        large_bags=body.large_bags,
        small_bags=body.small_bags,
        pickup=trip.pickup,
        car_type=body.car_type,
        price_inr=body.price_inr,
        status="OPEN",
    )
    db.add(req)
    db.commit()
    return req


def seed_open_requests(db: Session) -> int:
    """Insert the requests of open_requests.json that are not in the database yet."""
    added = 0
    for row in catalog().open_requests:
        if db.get(RideRequest, row["request_id"]):
            continue
        db.add(RideRequest(
            id=row["request_id"],
            traveler_name=row["traveler_name"],
            flight_id=row["flight_id"],
            hotel_id=row["hotel_id"],
            adults=row["adults"],
            child_ages=row.get("child_ages") or [],
            large_bags=row["large_bags"],
            small_bags=row["small_bags"],
            pickup=parse_dt(row["pickup"]),
            car_type=row.get("car_type"),
            price_inr=row["price_inr"],
            status="OPEN",
        ))
        added += 1
    db.commit()
    return added
