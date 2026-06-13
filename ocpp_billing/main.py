"""
OCPP 1.6 Charging Station Billing System
=========================================

REST API  : http://localhost:8000/docs
OCPP WS   : ws://localhost:8000/ocpp/<charge_point_id>
            (subprotocol: ocpp1.6)

Quick start:
    pip install -r requirements.txt
    python main.py
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from database import Base, SessionLocal, engine
from api import customers, tariffs, cards, sessions, charge_points, stats
from ocpp_handler import on_connect
import models  # noqa: F401 – required so SQLAlchemy registers all tables

STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _seed_default_tariff()
    yield


def _seed_default_tariff():
    """Create a sensible default tariff if none exists."""
    db = SessionLocal()
    try:
        if not db.query(models.Tariff).filter_by(is_default=True).first():
            db.add(models.Tariff(
                name="Standard",
                description="Default tariff – applies when no customer-specific tariff is defined",
                price_per_kwh=0.45,
                price_per_minute=0.0,
                connection_fee=1.00,
                blocking_fee_per_minute=0.10,
                blocking_grace_period_minutes=10,
                is_default=True,
            ))
            db.commit()
    finally:
        db.close()


app = FastAPI(
    title="OCPP Charging Station Billing System",
    description=(
        "Manages charging stations via OCPP 1.6, with per-customer tariffs, "
        "RFID card billing, and configurable Blockiergebühr (blocking fee)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(customers.router, prefix="/api/customers", tags=["Customers"])
app.include_router(tariffs.router, prefix="/api/tariffs", tags=["Tariffs"])
app.include_router(cards.router, prefix="/api/cards", tags=["Cards"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["Sessions"])
app.include_router(charge_points.router, prefix="/api/charge-points", tags=["Charge Points"])
app.include_router(stats.router, prefix="/api/stats", tags=["Statistics"])

# Serve the dashboard SPA
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.websocket("/ocpp/{charge_point_id}")
async def ocpp_endpoint(websocket: WebSocket, charge_point_id: str):
    """OCPP 1.6 WebSocket endpoint – one connection per charge point."""
    await on_connect(websocket, charge_point_id)


@app.get("/", tags=["Dashboard"], include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
