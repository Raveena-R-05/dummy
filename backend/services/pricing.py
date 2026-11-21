"""R3: suggested price range of a route, and the price check."""
from typing import Optional

from services.catalog import catalog
from services.errors import RuleError, violation


def get_route(airport: str, city: str, area: str) -> dict:
    route = catalog().routes.get((airport, city, area))
    if route is None:
        raise RuleError("R1", f"There is no route from {airport} to {city} / {area}.")
    return route


def price_range(route: dict) -> dict:
    return {"min": route["price_min_inr"], "max": route["price_max_inr"]}


def price_violation(price: int, route: dict, label: str = "Price") -> Optional[dict]:
    """None when the price is inside the range (both ends allowed), else a violation."""
    lo, hi = route["price_min_inr"], route["price_max_inr"]
    where = f"{route['airport']} to {route['city']} / {route['area']}"
    if price < lo:
        return violation(
            "R3", "PRICE_LOW",
            f"{label} ₹{price:,} is below the minimum ₹{lo:,} for {where}. "
            f"The allowed range is ₹{lo:,} to ₹{hi:,}.",
            min=lo, max=hi,
        )
    if price > hi:
        return violation(
            "R3", "PRICE_HIGH",
            f"{label} ₹{price:,} is above the maximum ₹{hi:,} for {where}. "
            f"The allowed range is ₹{lo:,} to ₹{hi:,}.",
            min=lo, max=hi,
        )
    return None


def check_price(price: int, route: dict, label: str = "Price") -> None:
    v = price_violation(price, route, label)
    if v:
        raise RuleError("R3", v["message"], 422, min=v["min"], max=v["max"])
