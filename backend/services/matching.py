"""Which suppliers can serve a request, and does a car fit?  (R1, R2, R4, R5, R6)"""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from services import availability, pricing
from services.catalog import MIN_PICKUP_GAP_MINUTES, catalog, earliest_pickup, parse_dt
from services.errors import RuleError, raise_violations, violation

CAR_TYPES = ["HATCHBACK", "SEDAN", "SUV", "BUS"]


def fmt(dt: datetime) -> str:
    return dt.strftime("%d %b %Y, %H:%M")


# ----------------------------------------------------------------------------
# Trip = flight + hotel + pickup, resolved against the catalog (R1, R2)
# ----------------------------------------------------------------------------
@dataclass
class Trip:
    flight: dict
    hotel: dict
    airport: str
    city: str
    area: str
    route: dict
    landing: datetime
    earliest_pickup: datetime
    pickup: datetime
    busy_start: datetime
    busy_end: datetime  # pickup + 2 x drive_minutes (R6)


def resolve_trip(
    flight_id: str,
    hotel_id: str,
    pickup: Optional[datetime] = None,
    enforce_r2: bool = True,
) -> Trip:
    cat = catalog()
    flight = cat.flights.get(flight_id)
    if flight is None:
        raise RuleError("R1", f"Flight '{flight_id}' is not in the catalog.")
    hotel = cat.hotels.get(hotel_id)
    if hotel is None:
        raise RuleError("R1", f"Hotel '{hotel_id}' is not in the catalog.")

    airport = cat.airports.get(flight["to"]) or {}
    serves = airport.get("serves_cities") or []
    if hotel["city"] not in serves:
        if serves:
            msg = (
                f"Flight {flight['flight_number']} lands at {airport['name']} ({flight['to']}), "
                f"which serves {', '.join(serves)}. {hotel['name']} is in {hotel['city']}, "
                "so the airport does not serve the hotel's city."
            )
        else:
            msg = (
                f"Flight {flight['flight_number']} lands at {flight['to']}, which has no taxi "
                "service on this platform. Choose a flight that arrives in Japan or the UAE."
            )
        raise RuleError("R1", msg)

    route = pricing.get_route(flight["to"], hotel["city"], hotel["area"])
    landing = parse_dt(flight["arrival_local"])
    earliest = earliest_pickup(flight)

    if pickup is None:
        pickup = earliest
    pickup = pickup.replace(tzinfo=None)
    if enforce_r2 and pickup < earliest:
        raise RuleError(
            "R2",
            f"Pickup {fmt(pickup)} is too early. The flight lands at {fmt(landing)}; "
            f"the pickup must be at least {MIN_PICKUP_GAP_MINUTES} minutes later, "
            f"so {fmt(earliest)} or later.",
            earliest_pickup=earliest,
        )

    return Trip(
        flight=flight, hotel=hotel, airport=flight["to"], city=hotel["city"], area=hotel["area"],
        route=route, landing=landing, earliest_pickup=earliest, pickup=pickup,
        busy_start=pickup, busy_end=pickup + timedelta(minutes=2 * route["drive_minutes"]),
    )


def validate_party(traveler_name: str, adults: int, child_ages: list[int],
                   large_bags: int, small_bags: int) -> None:
    """R1 (people) and basic value checks. Collects every problem, not just the first."""
    problems = []
    if not traveler_name or not traveler_name.strip():
        problems.append(violation("INVALID_VALUE", "NAME", "Traveler name is required."))
    if adults < 1:
        problems.append(violation("R1", "ADULTS", "At least 1 adult is required."))
    for age in child_ages:
        if age < 0 or age > 17:
            problems.append(violation(
                "R1", "CHILD_AGE",
                f"Child age {age} is not valid. A child is aged 0 to 17; "
                "anyone 18 or older counts as an adult.",
            ))
            break
    if large_bags < 0 or small_bags < 0:
        problems.append(violation("INVALID_VALUE", "BAGS", "Bag counts cannot be negative."))
    raise_violations(problems)


# ----------------------------------------------------------------------------
# Need = what a request asks of a car
# ----------------------------------------------------------------------------
@dataclass
class Need:
    trip: Trip
    passengers: int
    large_bags: int
    small_bags: int
    car_type: Optional[str]


def need_from_request(req) -> Need:
    """Build the Need of a stored request (R2 is not re-checked: it was checked at creation)."""
    trip = resolve_trip(req.flight_id, req.hotel_id, req.pickup, enforce_r2=False)
    return Need(
        trip=trip,
        passengers=req.adults + len(req.child_ages or []),
        large_bags=req.large_bags,
        small_bags=req.small_bags,
        car_type=req.car_type,
    )


# ----------------------------------------------------------------------------
# R4 / R5 / R6
# ----------------------------------------------------------------------------
def company_level_violations(company: dict, airport: str, city: str, area: str,
                             pickup: datetime) -> list[dict]:
    """R4: works at the airport, drives to the hotel's city and area, open at pickup."""
    name = company["name"]
    found = []
    if airport not in company["airports"]:
        found.append(violation("R4", "AIRPORT", f"{name} does not pick up at {airport}."))
    if not any(a["city"] == city and a["area"] == area for a in company["areas"]):
        found.append(violation("R4", "AREA", f"{name} does not drive to {city} / {area}."))
    if not availability.is_open(company["service_from"], company["service_until"], pickup.time()):
        found.append(violation(
            "R4", "HOURS",
            f"{name} is closed at {pickup:%H:%M} "
            f"(open {company['service_from']} to {company['service_until']}).",
        ))
    return found


def fit_violations(vehicle: dict, need: Need) -> list[dict]:
    """R5: car type (if the traveler chose one), seats, large bags, small bags."""
    vid, found = vehicle["vehicle_id"], []
    if need.car_type and vehicle["type"] != need.car_type:
        found.append(violation(
            "R5", "TYPE", f"Car {vid} is a {vehicle['type']}; the traveler asked for {need.car_type}."))
    if vehicle["seats"] < need.passengers:
        found.append(violation(
            "R5", "SEATS",
            f"Car {vid} has {vehicle['seats']} seats but the ride has {need.passengers} passengers "
            "(children included)."))
    if vehicle["large_bags"] < need.large_bags:
        found.append(violation(
            "R5", "LARGE_BAGS",
            f"Car {vid} fits {vehicle['large_bags']} large bags but the ride has {need.large_bags}."))
    if vehicle["small_bags"] < need.small_bags:
        found.append(violation(
            "R5", "SMALL_BAGS",
            f"Car {vid} fits {vehicle['small_bags']} small bags but the ride has {need.small_bags}."))
    return found


def vehicle_violations(db: Session, vehicle: dict, need: Need,
                       exclude_booking_id: Optional[int] = None) -> list[dict]:
    found = fit_violations(vehicle, need)
    conflict = availability.vehicle_conflict(
        db, vehicle["vehicle_id"], need.trip.busy_start, need.trip.busy_end, exclude_booking_id)
    if conflict:
        found.append(violation(
            "R6", "BUSY",
            f"Car {vehicle['vehicle_id']} is busy {fmt(conflict['start'])} to {fmt(conflict['end'])}, "
            f"which overlaps this ride ({fmt(need.trip.busy_start)} to {fmt(need.trip.busy_end)}).",
            conflict=conflict,
        ))
    return found


def evaluate_company(db: Session, company: dict, need: Need,
                     exclude_booking_id: Optional[int] = None) -> dict:
    """Full verdict for one supplier on one request, with the reason for every 'no'."""
    t = need.trip
    level = company_level_violations(company, t.airport, t.city, t.area, t.pickup)

    vehicles = []
    for vehicle in company["vehicles"]:
        v = vehicle_violations(db, vehicle, need, exclude_booking_id)
        vehicles.append({**vehicle, "eligible": not v, "violations": v})
    eligible_ids = [v["vehicle_id"] for v in vehicles if v["eligible"]]

    if level:
        code, summary = level[0]["code"], level[0]["message"]
    elif not eligible_ids:
        code, summary = "CAR", f"{company['name']} has no car that fits this ride and is free."
    else:
        code, summary = "OK", None

    return {
        "company_id": company["company_id"],
        "name": company["name"],
        "eligible": not level and bool(eligible_ids),
        "code": code,
        "summary": summary,
        "company_violations": level,
        "eligible_vehicle_ids": eligible_ids,
        "vehicles": vehicles,
    }


def evaluate_all(db: Session, need: Need) -> list[dict]:
    return [evaluate_company(db, c, need) for c in catalog().companies.values()]


def explain_unserved(evaluations: list[dict], need: Need) -> str:
    """Why no supplier can serve the request (M2), in one sentence."""
    t, counts = need.trip, Counter(e["code"] for e in evaluations)
    parts = []
    if counts["AIRPORT"]:
        parts.append(f"{counts['AIRPORT']} supplier(s) do not pick up at {t.airport}")
    if counts["AREA"]:
        parts.append(f"{counts['AREA']} do not drive to {t.city} / {t.area}")
    if counts["HOURS"]:
        parts.append(f"{counts['HOURS']} are closed at {t.pickup:%H:%M}")
    if counts["CAR"]:
        want = f" of type {need.car_type}" if need.car_type else ""
        parts.append(
            f"{counts['CAR']} have no car{want} that fits {need.passengers} passenger(s), "
            f"{need.large_bags} large and {need.small_bags} small bag(s) and is free "
            f"{fmt(t.busy_start)} to {fmt(t.busy_end)}")
    return "No supplier can serve this ride: " + "; ".join(parts) + "."


# ----------------------------------------------------------------------------
# R7: validate an assignment (supplier picks a car and a price)
# ----------------------------------------------------------------------------
def assignment_violations(db: Session, company: dict, vehicle_id: str, price: int,
                          need: Need) -> list[dict]:
    owner = catalog().vehicles.get(vehicle_id)
    if owner is None or owner[0] != company["company_id"]:
        return [violation("R4", "NOT_YOUR_CAR",
                          f"Car '{vehicle_id}' does not belong to {company['name']}.")]
    t = need.trip
    found = company_level_violations(company, t.airport, t.city, t.area, t.pickup)  # R4
    found += vehicle_violations(db, owner[1], need)                                  # R5, R6
    price_problem = pricing.price_violation(price, t.route, "Supplier price")        # R3
    if price_problem:
        found.append(price_problem)
    return found
