from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
import models
import schemas

router = APIRouter()


@router.get("/", response_model=list[schemas.SessionOut])
def list_sessions(
    status: str | None = None,
    customer_id: int | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.ChargingSession)
    if status:
        q = q.filter_by(status=status)
    if customer_id:
        q = q.filter_by(customer_id=customer_id)
    return q.order_by(models.ChargingSession.id.desc()).all()


@router.get("/{session_id}", response_model=schemas.SessionOut)
def get_session(session_id: int, db: Session = Depends(get_db)):
    s = db.query(models.ChargingSession).filter_by(id=session_id).first()
    if not s:
        raise HTTPException(404, "Session not found")
    return s


@router.get("/{session_id}/invoice", response_model=schemas.InvoiceOut)
def get_invoice(session_id: int, db: Session = Depends(get_db)):
    """Generate a structured invoice for a completed charging session."""
    s = db.query(models.ChargingSession).filter_by(id=session_id).first()
    if not s:
        raise HTTPException(404, "Session not found")

    cp = s.charge_point
    tariff = s.tariff

    return schemas.InvoiceOut(
        session_id=s.id,
        transaction_id=s.transaction_id,
        charge_point_id=cp.charge_point_id if cp else None,
        connector_id=s.connector_id,
        customer_name=s.customer.name if s.customer else None,
        customer_email=s.customer.email if s.customer else None,
        card_rfid=s.card.rfid_tag if s.card else None,
        tariff_name=tariff.name if tariff else None,
        start_time=s.start_time,
        end_time=s.end_time,
        energy_kwh=s.energy_kwh,
        duration_minutes=s.duration_minutes,
        charging_minutes=s.charging_minutes,
        blocking_minutes=s.blocking_minutes,
        blocking_grace_period_minutes=tariff.blocking_grace_period_minutes if tariff else 0,
        price_per_kwh=tariff.price_per_kwh if tariff else 0.0,
        price_per_minute=tariff.price_per_minute if tariff else 0.0,
        connection_fee=tariff.connection_fee if tariff else 0.0,
        blocking_fee_per_minute=tariff.blocking_fee_per_minute if tariff else 0.0,
        cost_energy=s.cost_energy,
        cost_time=s.cost_time,
        cost_connection=s.cost_connection,
        cost_blocking=s.cost_blocking,
        total_cost=s.total_cost,
        status=s.status,
        stop_reason=s.stop_reason,
    )
