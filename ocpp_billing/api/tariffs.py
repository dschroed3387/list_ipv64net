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
        # Clear existing default
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
