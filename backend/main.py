"""Rideport API: airport taxi ride offers.

Run:  uvicorn main:app --reload --port 8000      (from the backend/ folder)
Docs: http://localhost:8000/docs
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from database import SessionLocal, init_db
from routers import bookings, offers, reference, requests, suppliers
from services.catalog import catalog
from services.errors import RuleError
from services.ride_requests import seed_open_requests


@asynccontextmanager
async def lifespan(app: FastAPI):
    catalog()        # load + check the JSON files at startup
    init_db()        # create tables if missing (data survives restarts)
    with SessionLocal() as db:
        seed_open_requests(db)   # the 3 open requests of the data pack
    yield


app = FastAPI(title="Rideport API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RuleError)
async def rule_error_handler(_: Request, exc: RuleError):
    return JSONResponse(status_code=exc.status_code,
                        content=jsonable_encoder({"detail": exc.to_dict()}))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    """A value with the wrong type or shape: one readable message."""
    problems = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"] if p not in ("body", "query", "path"))
        problems.append({"field": field, "message": err["msg"]})
    message = "; ".join(f"{p['field']}: {p['message']}" if p["field"] else p["message"]
                        for p in problems)
    return JSONResponse(status_code=422, content={"detail": {
        "rule": "VALIDATION", "message": f"Invalid value. {message}", "errors": problems}})


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


for module in (reference, requests, offers, bookings, suppliers):
    app.include_router(module.router)
