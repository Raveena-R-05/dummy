MENON = dict(traveler_name="Menon family", flight_id="FL-401", hotel_id="HTL-TYO-004",
             adults=2, child_ages=[6], large_bags=3, small_bags=2,
             pickup="2027-04-10T11:30", price_inr=12000)


def post_menon(client, **override):
    return client.post("/requests", json={**MENON, **override})


def assign(client, company, req, vehicle, price, **extra):
    return client.post(f"/suppliers/{company}/requests/{req}/offers",
                       json={"vehicle_id": vehicle, "price_inr": price, **extra})


def rule(resp):
    return resp.json()["detail"]["rule"]


# ---------------- M1: request validation ----------------
def test_price_range_for_menon(client):
    r = client.get("/reference/price-range", params={"flight_id": "FL-401", "hotel_id": "HTL-TYO-004"})
    assert r.status_code == 200
    body = r.json()
    assert (body["price_min_inr"], body["price_max_inr"]) == (10200, 16800)
    assert body["earliest_pickup"].startswith("2027-04-10T11:30")


def test_menon_request_created(client):
    r = post_menon(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] == "REQ-0004"          # 3 seeded requests come first
    assert body["can_be_served"] is True
    assert body["passengers"] == 3
    assert body["busy_end"].startswith("2027-04-10T14:30")


def test_price_below_and_above_range_refused(client):
    low = post_menon(client, price_inr=10199)
    high = post_menon(client, price_inr=16801)
    assert low.status_code == high.status_code == 422
    assert rule(low) == rule(high) == "R3"
    assert low.json()["detail"]["min"] == 10200 and low.json()["detail"]["max"] == 16800
    assert post_menon(client, price_inr=10200).status_code == 201   # both ends allowed
    assert post_menon(client, price_inr=16800).status_code == 201


def test_pickup_before_landing_plus_60_refused(client):
    r = post_menon(client, pickup="2027-04-10T11:29")
    assert r.status_code == 422 and rule(r) == "R2"


def test_pickup_defaults_to_earliest(client):
    body = post_menon(client, pickup=None).json()
    assert body["pickup"].startswith("2027-04-10T11:30")


def test_r1_rules(client):
    assert rule(post_menon(client, adults=0)) == "R1"
    assert rule(post_menon(client, child_ages=[18])) == "R1"
    assert post_menon(client, child_ages=[0, 17]).status_code == 201
    assert rule(post_menon(client, flight_id="FL-NOPE")) == "R1"
    assert rule(post_menon(client, hotel_id="HTL-OSA-001")) == "R1"   # NRT does not serve Osaka
    r = post_menon(client, adults="two")
    assert r.status_code == 422 and rule(r) == "VALIDATION"


# ---------------- M2: who sees what ----------------
def test_seeded_requests_visible_only_to_capable_suppliers(client):
    ids = lambda cid: {r["id"] for r in client.get(f"/suppliers/{cid}/requests").json()}
    assert ids("TX-JP-01") == {"REQ-0001"}                 # Sakura: Tokyo only
    assert ids("TX-AE-02") == {"REQ-0003"}                 # Desert Rose: Abu Dhabi
    assert ids("TX-JP-05") == set()                        # Kansai Airport Taxi: sees nothing


def test_seeded_request_nobody_can_serve_says_why(client):
    r = client.get("/requests/REQ-0002").json()            # KIX -> Namba, SEDAN
    assert r["can_be_served"] is False
    assert "do not pick up at KIX" in r["no_supplier_reason"]


def test_dashboard_menon_and_details(client):
    post_menon(client)
    dash = client.get("/suppliers/TX-JP-01/requests").json()
    menon = next(r for r in dash if r["id"] == "REQ-0004")
    assert menon["child_ages"] == [6] and menon["large_bags"] == 3
    # SC-2 is busy (RIDE-0001), SC-1 is too small -> only SC-3 is eligible
    assert menon["eligible_vehicle_ids"] == ["SC-3"]


def test_no_supplier_can_serve_reason(client):
    # 20 people, 10 large bags: no car fits anywhere
    r = post_menon(client, adults=20, large_bags=10)
    body = r.json()
    assert r.status_code == 201 and body["can_be_served"] is False
    assert "No supplier can serve" in body["no_supplier_reason"]


# ---------------- M3 / R7: assign ----------------
def test_assign_refusals_name_the_rule(client):
    post_menon(client)
    busy = assign(client, "TX-JP-01", "REQ-0004", "SC-2", 13000)
    assert busy.status_code == 422 and rule(busy) == "R6"
    small = assign(client, "TX-JP-01", "REQ-0004", "SC-1", 13000)
    assert rule(small) == "R5"
    price = assign(client, "TX-JP-01", "REQ-0004", "SC-3", 20000)
    assert rule(price) == "R3"
    other = assign(client, "TX-JP-01", "REQ-0004", "KA-1", 13000)   # not Sakura's car
    assert rule(other) == "R4"
    wrong_airport = assign(client, "TX-AE-01", "REQ-0004", "FT-1", 13000)
    assert rule(wrong_airport) == "R4"
    ok = assign(client, "TX-JP-01", "REQ-0004", "SC-3", 13000)
    assert ok.status_code == 201 and ok.json()["status"] == "OPEN"
    assert rule(assign(client, "TX-JP-01", "REQ-0004", "SC-3", 13000)) == "DUPLICATE"


def test_busy_boundary_touching_is_free(client):
    # SC-2 busy 11:00-14:00 on 10 Apr. A ride ending exactly at 11:00 is fine,
    # a ride starting exactly at 14:00 is fine. NRT->Ueno busy time is 3h.
    post_menon(client, pickup="2027-04-10T14:00")
    assert assign(client, "TX-JP-01", "REQ-0004", "SC-2", 13000).status_code == 201


# ---------------- M4 / M5 / M6 / R8: book ----------------
def full_menon_booking(client):
    post_menon(client)
    o1 = assign(client, "TX-JP-01", "REQ-0004", "SC-3", 13000).json()
    # other Tokyo/NRT suppliers (suppliers that can serve)
    others = [r for r in client.get("/requests/REQ-0004").json()["serving_suppliers"]]
    return o1, others


def test_book_reject_not_chosen_and_summary(client):
    o1, others = full_menon_booking(client)
    # a second supplier assigns too
    second = next(s for s in others if s["company_id"] != "TX-JP-01")
    veh = client.get(f"/suppliers/{second['company_id']}/requests/REQ-0004").json()
    car = next(v for v in veh["vehicles"] if v["eligible"])
    o2 = assign(client, second["company_id"], "REQ-0004", car["vehicle_id"], 14000).json()

    assert client.post(f"/offers/{o2['id']}/reject").json()["status"] == "REJECTED"
    b = client.post(f"/offers/{o1['id']}/book")
    assert b.status_code == 201
    number = b.json()["booking_number"]
    assert len(number) == 10 and number.isdigit()

    # rejected taxi cannot be booked
    again = client.post(f"/offers/{o2['id']}/book")
    assert again.status_code == 409 and rule(again) == "R8"

    # summary works, and persists (same DB)
    s = client.get(f"/bookings/{number}").json()
    assert s["supplier"]["name"] == "Sakura Cabs" and s["car"]["vehicle_id"] == "SC-3"
    assert s["price_inr"] == 13000 and s["hotel"]["name"] == "Ueno Garden Inn"
    assert client.get("/bookings/1234567890").status_code == 404
    assert client.get("/bookings/abc").status_code == 404

    # request is closed, offers listed with statuses
    assert client.get("/requests/REQ-0004").json()["status"] == "BOOKED"
    statuses = {o["id"]: o["status"] for o in client.get("/requests/REQ-0004/offers").json()}
    assert statuses[o1["id"]] == "BOOKED" and statuses[o2["id"]] == "REJECTED"


def test_not_chosen(client):
    o1, others = full_menon_booking(client)
    second = next(s for s in others if s["company_id"] != "TX-JP-01")
    veh = client.get(f"/suppliers/{second['company_id']}/requests/REQ-0004").json()
    car = next(v for v in veh["vehicles"] if v["eligible"])
    o2 = assign(client, second["company_id"], "REQ-0004", car["vehicle_id"], 14000).json()
    client.post(f"/offers/{o1['id']}/book")
    assert client.get(f"/offers/{o2['id']}").json()["status"] == "NOT_CHOSEN"
    assert rule(client.post(f"/offers/{o2['id']}/book")) == "R8"


def test_double_booking_refused_m6(client):
    # Two requests with overlapping times; supplier offers the SAME car to both.
    post_menon(client)                                           # REQ-0004 11:30-14:30
    post_menon(client, traveler_name="Other", pickup="2027-04-10T12:00")  # REQ-0005 overlaps
    a = assign(client, "TX-JP-01", "REQ-0004", "SC-3", 13000).json()
    b = assign(client, "TX-JP-01", "REQ-0005", "SC-3", 13000).json()
    assert client.post(f"/offers/{a['id']}/book").status_code == 201
    r = client.post(f"/offers/{b['id']}/book")
    assert r.status_code == 409 and rule(r) == "R6"
    # the offer view warns the traveler too
    assert client.get(f"/offers/{b['id']}").json()["can_book"] is False
    # and the car is no longer assignable to a third overlapping request
    post_menon(client, traveler_name="Third", pickup="2027-04-10T13:00")
    assert rule(assign(client, "TX-JP-01", "REQ-0006", "SC-3", 13000)) == "R6"


def test_offer_expiry_g4(client):
    post_menon(client)
    past = assign(client, "TX-JP-01", "REQ-0004", "SC-3", 13000, expires_at="2020-01-01T00:00")
    assert past.status_code == 422 and rule(past) == "G4"
    o = assign(client, "TX-JP-01", "REQ-0004", "SC-3", 13000, expires_in_minutes=30).json()
    assert o["expires_at"] is not None
    # force the end time into the past directly in the DB, then try to book
    from datetime import datetime, timedelta
    from database import SessionLocal
    from models import Offer
    with SessionLocal() as db:
        db.get(Offer, o["id"]).expires_at = datetime.now() - timedelta(minutes=1)
        db.commit()
    r = client.post(f"/offers/{o['id']}/book")
    assert r.status_code == 409 and rule(r) == "G4"
    assert client.get(f"/offers/{o['id']}").json()["status"] == "EXPIRED"


def test_sort_and_filter_g5(client):
    post_menon(client)
    assign(client, "TX-JP-01", "REQ-0004", "SC-3", 15000)
    veh = client.get("/suppliers/TX-JP-03/requests/REQ-0004").json()   # Edo Premium
    car = next(v for v in veh["vehicles"] if v["eligible"])
    assert assign(client, "TX-JP-03", "REQ-0004", car["vehicle_id"], 11000).status_code == 201
    asc = [o["price_inr"] for o in client.get("/requests/REQ-0004/offers?sort=price_asc").json()]
    desc = [o["price_inr"] for o in client.get("/requests/REQ-0004/offers?sort=price_desc").json()]
    assert asc == [11000, 15000] and desc == [15000, 11000]
    only = client.get(f"/requests/REQ-0004/offers?car_type={car['type'].lower()}").json()
    assert only and all(o["car"]["type"] == car["type"] for o in only)
    assert client.get("/requests/REQ-0004/offers?car_type=BUS").json() == []


# ---------------- M7 / R9: change requests ----------------
def booked_menon(client):
    post_menon(client)
    o = assign(client, "TX-JP-01", "REQ-0004", "SC-3", 13000).json()
    return client.post(f"/offers/{o['id']}/book").json()["booking_number"]


def test_change_pickup_accept(client):
    number = booked_menon(client)
    r = client.post(f"/bookings/{number}/change-requests", json={"new_pickup": "2027-04-10T16:00"})
    assert r.status_code == 201 and r.json()["status"] == "WAITING"
    cid = r.json()["id"]
    # supplier sees it
    waiting = client.get("/suppliers/TX-JP-01/change-requests").json()
    assert [c["id"] for c in waiting] == [cid]
    ok = client.post(f"/suppliers/TX-JP-01/change-requests/{cid}/accept")
    assert ok.status_code == 200 and ok.json()["status"] == "ACCEPTED"
    s = client.get(f"/bookings/{number}").json()
    assert s["pickup"].startswith("2027-04-10T16:00")
    assert s["busy_end"].startswith("2027-04-10T19:00")
    # cannot decide twice
    assert client.post(f"/suppliers/TX-JP-01/change-requests/{cid}/reject").status_code == 409


def test_change_new_flight_defaults_to_landing_plus_60(client):
    number = booked_menon(client)
    flights = [f for f in client.get("/reference/flights", params={"airport": "NRT", "date": "2027-04-11"}).json()]
    f = flights[0]
    r = client.post(f"/bookings/{number}/change-requests", json={"new_flight_id": f["flight_id"]})
    assert r.status_code == 201
    assert r.json()["new_pickup"].startswith(f["earliest_pickup"][:16])


def test_change_refused_by_platform(client):
    number = booked_menon(client)
    early = client.post(f"/bookings/{number}/change-requests", json={"new_pickup": "2027-04-10T10:00"})
    assert early.status_code == 422 and rule(early) == "R2"
    closed = client.post(f"/bookings/{number}/change-requests", json={"new_pickup": "2027-04-11T03:00"})
    assert closed.status_code == 422 and rule(closed) == "R4"      # Sakura opens 06:00
    empty = client.post(f"/bookings/{number}/change-requests", json={})
    assert empty.status_code == 422
    assert client.post("/bookings/9999999999/change-requests", json={"new_pickup": "2027-04-10T16:00"}).status_code == 404


def test_change_accept_refused_when_car_busy_then_reject_keeps_booking(client):
    number = booked_menon(client)
    # another booking takes SC-3 in the afternoon
    post_menon(client, traveler_name="Later", pickup="2027-04-10T16:00")
    o = assign(client, "TX-JP-01", "REQ-0005", "SC-3", 13000).json()
    assert client.post(f"/offers/{o['id']}/book").status_code == 201

    c = client.post(f"/bookings/{number}/change-requests", json={"new_pickup": "2027-04-10T17:00"}).json()
    acc = client.post(f"/suppliers/TX-JP-01/change-requests/{c['id']}/accept")
    assert acc.status_code == 409 and rule(acc) == "R6"
    assert client.get(f"/bookings/{number}").json()["pickup"].startswith("2027-04-10T11:30")

    rej = client.post(f"/suppliers/TX-JP-01/change-requests/{c['id']}/reject", json={"reason": "Car busy"})
    assert rej.json()["status"] == "REJECTED"
    s = client.get(f"/bookings/{number}").json()
    assert s["pickup"].startswith("2027-04-10T11:30")          # old booking kept
    assert s["change_requests"][0]["reason"] == "Car busy"


def test_wrong_supplier_cannot_decide_change(client):
    number = booked_menon(client)
    c = client.post(f"/bookings/{number}/change-requests", json={"new_pickup": "2027-04-10T16:00"}).json()
    assert client.post(f"/suppliers/TX-JP-02/change-requests/{c['id']}/accept").status_code == 404


def test_survives_restart(client):
    number = booked_menon(client)
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as fresh:   # new lifespan = "backend restart", same DB
        assert fresh.get(f"/bookings/{number}").status_code == 200
        assert len(fresh.get("/requests").json()) == 4          # seeds not duplicated
