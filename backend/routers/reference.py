"""Read-only catalog data for the forms (flights, hotels, price range)."""
from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter

from services import matching
from services.catalog import catalog, parse_dt
from services.presenters import flight_view, hotel_view

router = APIRouter(prefix="/reference", tags=["reference"])


@router.get("/airports")
def airports():
    """Airports that receive arrivals (serve at least one city)."""
    return [a for a in catalog().airports.values() if a.get("serves_cities")]


@router.get("/flights")
def flights(airport: Optional[str] = None, date: Optional[date_type] = None,
            hotel_id: Optional[str] = None):
    """Arrival flights (NRT, HND, KIX, DXB, AUH). Filter by airport, arrival date,
    or hotel (only flights whose airport serves the hotel's city)."""
    cat = catalog()
    result = cat.arrival_flights()
    if airport:
        result = [f for f in result if f["to"] == airport.upper()]
    if date:
        result = [f for f in result if parse_dt(f["arrival_local"]).date() == date]
    if hotel_id and hotel_id in cat.hotels:
        city = cat.hotels[hotel_id]["city"]
        result = [f for f in result if city in cat.airports[f["to"]]["serves_cities"]]
    result.sort(key=lambda f: f["arrival_local"])
    return [flight_view(f) for f in result]


@router.get("/hotels")
def hotels(city: Optional[str] = None, airport: Optional[str] = None):
    cat = catalog()
    result = list(cat.hotels.values())
    if city:
        result = [h for h in result if h["city"].lower() == city.lower()]
    if airport:
        served = (cat.airports.get(airport.upper()) or {}).get("serves_cities") or []
        result = [h for h in result if h["city"] in served]
    return [hotel_view(h) for h in result]


@router.get("/car-types")
def car_types():
    return matching.CAR_TYPES


@router.get("/price-range")
def price_range(flight_id: str, hotel_id: str):
    """The suggested range for the route (M1). Also checks R1 and gives the earliest pickup (R2)."""
    trip = matching.resolve_trip(flight_id, hotel_id, None)
    return {
        "airport": trip.airport, "city": trip.city, "area": trip.area,
        "price_min_inr": trip.route["price_min_inr"], "price_max_inr": trip.route["price_max_inr"],
        "drive_minutes": trip.route["drive_minutes"], "distance_km": trip.route["distance_km"],
        "landing": trip.landing, "earliest_pickup": trip.earliest_pickup,
    }
