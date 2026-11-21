# Rideport: Airport Taxi Ride Offers

Travelers post an airport-to-hotel ride request with their own price. Taxi suppliers
see the requests they can serve and assign a car and a price. The traveler books one
taxi, rejects the others, and gets a 10-digit booking number.

Stack: **FastAPI + SQLAlchemy + PostgreSQL** (backend), **Next.js** (frontend, next phase).

## Start the backend (2 commands + a database)

```bash
docker compose up -d                       # PostgreSQL on localhost:5432
cd backend && pip install -r requirements.txt && cp .env.example .env && uvicorn main:app --reload --port 8000
```

API docs (try every endpoint): http://localhost:8000/docs

Tables are created and the 3 open requests are loaded automatically at startup.
Data survives a backend restart (it lives in PostgreSQL).

Run the tests (they use a temporary SQLite file, no database needed):
```bash
cd backend && pytest -q
```

## Architecture

```
backend/
  main.py            app, CORS, error handlers, startup (create tables + seed)
  database.py        engine, session, Base (DATABASE_URL from .env)
  models/            SQLAlchemy tables: RideRequest, Offer, Booking, ChangeRequest
  schemas/           Pydantic input models (types only; rules live in services)
  routers/           thin HTTP layer: reference, requests, offers, bookings, suppliers
  services/
    catalog.py       loads the read-only JSON files once
    pricing.py       R3  price range
    availability.py  R6  car free / busy;  opening hours (part of R4)
    matching.py      R1, R2, R4, R5  trip validation, who sees a request, does a car fit
    booking.py       R7, R8, R9, M6  assign, book, reject, change requests
    ride_requests.py create a request, seed open_requests.json
    presenters.py    rows -> JSON for the frontend
  data/              the provided JSON files (never modified)
  tests/             23 tests of the rules and the full Menon flow
```

JSON files hold the reference data (flights, hotels, suppliers, cars, routes, pre-booked rides).
PostgreSQL holds what the app creates: requests, offers (assigned taxis), bookings, change requests.

Relations: `ride_requests 1-N offers`, `offers 1-1 bookings`, `bookings 1-N change_requests`.

## Rules in the code

| Rule | Where |
|---|---|
| R1 flight/hotel exist, airport serves city, 1+ adult, child 0-17 | `matching.resolve_trip`, `matching.validate_party` |
| R2 pickup >= landing + 60 min | `matching.resolve_trip` |
| R3 price inside the route range | `pricing.price_violation` |
| R4 supplier works at airport, area, open at pickup | `matching.company_level_violations` |
| R5 seats, large bags, small bags, car type | `matching.fit_violations` |
| R6 busy = pickup to pickup + 2 x drive; no overlap; booked_rides count | `availability.vehicle_conflict` |
| R7 assign refuses and names the rule | `matching.assignment_violations`, `booking.assign_offer` |
| R8 book/reject, 10-digit number, others "not chosen" | `booking.book_offer`, `booking.reject_offer` |
| R9 change request, accept only if R2 + car free | `booking.create_change_request`, `booking.accept_change` |

Errors always look like `{"detail": {"rule": "R3", "message": "...", ...}}`.

## API summary

| Who | Endpoint | Purpose |
|---|---|---|
| any | `GET /reference/flights?airport=&date=&hotel_id=` | arrival flights |
| any | `GET /reference/hotels?city=&airport=` | hotels |
| traveler | `GET /reference/price-range?flight_id=&hotel_id=` | suggested range + earliest pickup |
| traveler | `POST /requests` | post a request (M1) |
| traveler | `GET /requests/{id}` , `GET /requests?traveler_name=` | status, "no supplier" reason (M2) |
| traveler | `GET /requests/{id}/offers?sort=&car_type=` | taxis from all suppliers (M4, G5) |
| traveler | `POST /offers/{id}/book`, `POST /offers/{id}/reject` | book or reject (M4) |
| traveler | `GET /bookings/{number}` | summary (M5) |
| traveler | `POST /bookings/{number}/change-requests` | new flight or pickup (M7) |
| supplier | `GET /suppliers` | choose who you are |
| supplier | `GET /suppliers/{id}/requests` | requests this supplier can serve (M2) |
| supplier | `GET /suppliers/{id}/requests/{rid}` | details + every car with why it fits or not |
| supplier | `POST /suppliers/{id}/requests/{rid}/offers` | assign a car + price (M3, G1, G4) |
| supplier | `GET /suppliers/{id}/offers`, `/bookings` | my taxis and bookings |
| supplier | `GET /suppliers/{id}/change-requests` | waiting change requests |
| supplier | `POST /suppliers/{id}/change-requests/{cid}/accept` or `/reject` | decide (M7) |

## Features done

Must: M1, M2, M3, M4, M5, M6, M7. Good: G1 (several cars: assign again with another car),
G2 (car type on the request), G4 (offer expiry), G5 (sort and filter).

## Design decisions and known limitations

- Times are local naive datetimes (no time zones), as the data dictionary says.
- A car is busy only because of **bookings** and `booked_rides.json`. Several suppliers' offers
  (even the same car for two requests) can exist at once; the car is checked again when the
  traveler books (M6).
- A change request with a new flight but no pickup uses landing + 60 minutes of the new flight.
  The platform refuses at once what can never work (R1, R2, supplier closed, price outside the
  new route's range). Whether the car is free is checked when the supplier accepts; if it is not,
  accept is refused and the supplier can reject.
- Offer expiry (`expires_at`) is compared with the server clock.
- Not built: shared ride (S1). No locking for simultaneous bookings (not required).
- Tables are created with `create_all` (no migrations). Change a model => drop the table or database.
