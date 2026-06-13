from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
import models
import schemas

router = APIRouter()


@router.get("/", response_model=list[schemas.ChargePointOut])
def list_charge_points(db: Session = Depends(get_db)):
    return db.query(models.ChargePoint).all()


@router.get("/{cp_id}", response_model=schemas.ChargePointOut)
def get_charge_point(cp_id: int, db: Session = Depends(get_db)):
    cp = db.query(models.ChargePoint).filter_by(id=cp_id).first()
    if not cp:
        raise HTTPException(404, "Charge point not found")
    return cp


@router.get("/{cp_id}/sessions", response_model=list[schemas.SessionOut])
def charge_point_sessions(cp_id: int, db: Session = Depends(get_db)):
    if not db.query(models.ChargePoint).filter_by(id=cp_id).first():
        raise HTTPException(404, "Charge point not found")
    return (
        db.query(models.ChargingSession)
        .filter_by(charge_point_db_id=cp_id)
        .order_by(models.ChargingSession.id.desc())
        .all()
    )
