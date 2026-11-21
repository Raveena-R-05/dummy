"""Read-only reference data loaded once from the provided JSON files.

The files are never modified. Set DATA_DIR to point at another copy
(e.g. the judges' original files); the folder layout must stay:
    <DATA_DIR>/catalog/{airports,flights,hotels}.json
    <DATA_DIR>/problem-2/{taxi_companies,routes,booked_rides,open_requests}.json
"""
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
MIN_PICKUP_GAP_MINUTES = 60  # R2


def parse_dt(value: str) -> datetime:
    """'YYYY-MM-DDTHH:MM[:SS]' -> naive datetime (all times are local, no time zones)."""
    return datetime.fromisoformat(value).replace(tzinfo=None)


def earliest_pickup(flight: dict) -> datetime:
    return parse_dt(flight["arrival_local"]) + timedelta(minutes=MIN_PICKUP_GAP_MINUTES)


def _load(relative: str):
    with open(DATA_DIR / relative, encoding="utf-8") as fh:
        return json.load(fh)


class Catalog:
    def __init__(self) -> None:
        self.airports = {a["code"]: a for a in _load("catalog/airports.json")}
        self.flights = {f["flight_id"]: f for f in _load("catalog/flights.json")}
        self.hotels = {h["hotel_id"]: h for h in _load("catalog/hotels.json")}
        self.routes = {
            (r["airport"], r["city"], r["area"]): r for r in _load("problem-2/routes.json")
        }
        self.companies = {c["company_id"]: c for c in _load("problem-2/taxi_companies.json")}
        self.open_requests = _load("problem-2/open_requests.json")

        # vehicle_id -> (company_id, vehicle dict)
        self.vehicles: dict[str, tuple[str, dict]] = {}
        for company in self.companies.values():
            for vehicle in company["vehicles"]:
                self.vehicles[vehicle["vehicle_id"]] = (company["company_id"], vehicle)

        # Cars kept busy by rides booked outside the platform (R6)
        self.fixed_busy: dict[str, list[tuple[datetime, datetime, str]]] = defaultdict(list)
        for ride in _load("problem-2/booked_rides.json"):
            self.fixed_busy[ride["vehicle_id"]].append(
                (parse_dt(ride["start"]), parse_dt(ride["end"]), ride["ride_id"])
            )

    def arrival_flights(self) -> list[dict]:
        """Flights that land at an airport this platform serves (NRT, HND, KIX, DXB, AUH)."""
        return [
            f
            for f in self.flights.values()
            if (self.airports.get(f["to"]) or {}).get("serves_cities")
        ]


@lru_cache(maxsize=1)
def catalog() -> Catalog:
    return Catalog()
