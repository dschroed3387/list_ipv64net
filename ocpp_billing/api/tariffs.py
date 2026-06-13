from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
import models
import schemas

router = APIRouter()


@router.post("/", response_model=schemas.TariffOut, status_code=201)
def create_tariff(body: schemas.TariffCreate, db: Session = Depends(get_db)):
    if body.customer_id:
        if not db.query(models.Customer).filter_by(id=body.customer_id).first():
            raise HTTPException(404, "Customer not found")
        if db.query(models.Tariff).filter_by(customer_id=body.customer_id).first():
            raise HTTPException(409, "Customer already has a tariff")

    if body.is_default:
        db.query(models.Tariff).filter_by(is_default=True).update({"is_default": False})

    tariff = models.Tariff(**body.model_dump())
    db.add(tariff)
    db.commit()
    db.refresh(tariff)
    return tariff


@router.get("/", response_model=list[schemas.TariffOut])
def list_tariffs(db: Session = Depends(get_db)):
    return db.query(models.Tariff).all()


@router.get("/{tariff_id}", response_model=schemas.TariffOut)
def get_tariff(tariff_id: int, db: Session = Depends(get_db)):
    t = db.query(models.Tariff).filter_by(id=tariff_id).first()
    if not t:
        raise HTTPException(404, "Tariff not found")
    return t


@router.put("/{tariff_id}", response_model=schemas.TariffOut)
def update_tariff(tariff_id: int, body: schemas.TariffUpdate, db: Session = Depends(get_db)):
    t = db.query(models.Tariff).filter_by(id=tariff_id).first()
    if not t:
        raise HTTPException(404, "Tariff not found")

    if body.is_default is True:
        db.query(models.Tariff).filter(models.Tariff.id != tariff_id).update({"is_default": False})

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(t, field, value)
    db.commit()
    db.refresh(t)
    return t


@router.delete("/{tariff_id}", status_code=204)
def delete_tariff(tariff_id: int, db: Session = Depends(get_db)):
    t = db.query(models.Tariff).filter_by(id=tariff_id).first()
    if not t:
        raise HTTPException(404, "Tariff not found")
    db.delete(t)
    db.commit()


# ── TariffPeriods (dynamic pricing windows) ───────────────────────────────────

@router.post("/{tariff_id}/periods", response_model=schemas.TariffPeriodOut, status_code=201)
def create_period(
    tariff_id: int, body: schemas.TariffPeriodCreate, db: Session = Depends(get_db)
):
    if not db.query(models.Tariff).filter_by(id=tariff_id).first():
        raise HTTPException(404, "Tariff not found")
    period = models.TariffPeriod(tariff_id=tariff_id, **body.model_dump())
    db.add(period)
    db.commit()
    db.refresh(period)
    return period


@router.get("/{tariff_id}/periods", response_model=list[schemas.TariffPeriodOut])
def list_periods(tariff_id: int, db: Session = Depends(get_db)):
    if not db.query(models.Tariff).filter_by(id=tariff_id).first():
        raise HTTPException(404, "Tariff not found")
    return (
        db.query(models.TariffPeriod)
        .filter_by(tariff_id=tariff_id)
        .order_by(models.TariffPeriod.priority.desc())
        .all()
    )


@router.put("/{tariff_id}/periods/{period_id}", response_model=schemas.TariffPeriodOut)
def update_period(
    tariff_id: int, period_id: int,
    body: schemas.TariffPeriodUpdate,
    db: Session = Depends(get_db),
):
    p = db.query(models.TariffPeriod).filter_by(id=period_id, tariff_id=tariff_id).first()
    if not p:
        raise HTTPException(404, "Period not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(p, field, value)
    db.commit()
    db.refresh(p)
    return p


@router.delete("/{tariff_id}/periods/{period_id}", status_code=204)
def delete_period(tariff_id: int, period_id: int, db: Session = Depends(get_db)):
    p = db.query(models.TariffPeriod).filter_by(id=period_id, tariff_id=tariff_id).first()
    if not p:
        raise HTTPException(404, "Period not found")
    db.delete(p)
    db.commit()
