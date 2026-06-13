from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
import models
import schemas

router = APIRouter()


@router.post("/", response_model=schemas.CustomerOut, status_code=201)
def create_customer(body: schemas.CustomerCreate, db: Session = Depends(get_db)):
    if db.query(models.Customer).filter_by(email=body.email).first():
        raise HTTPException(409, "Email already registered")
    customer = models.Customer(**body.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/", response_model=list[schemas.CustomerOut])
def list_customers(db: Session = Depends(get_db)):
    return db.query(models.Customer).all()


@router.get("/{customer_id}", response_model=schemas.CustomerOut)
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    c = db.query(models.Customer).filter_by(id=customer_id).first()
    if not c:
        raise HTTPException(404, "Customer not found")
    return c


@router.put("/{customer_id}", response_model=schemas.CustomerOut)
def update_customer(customer_id: int, body: schemas.CustomerUpdate, db: Session = Depends(get_db)):
    c = db.query(models.Customer).filter_by(id=customer_id).first()
    if not c:
        raise HTTPException(404, "Customer not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(c, field, value)
    db.commit()
    db.refresh(c)
    return c


@router.delete("/{customer_id}", status_code=204)
def delete_customer(customer_id: int, db: Session = Depends(get_db)):
    c = db.query(models.Customer).filter_by(id=customer_id).first()
    if not c:
        raise HTTPException(404, "Customer not found")
    db.delete(c)
    db.commit()


@router.get("/{customer_id}/sessions", response_model=list[schemas.SessionOut])
def customer_sessions(customer_id: int, db: Session = Depends(get_db)):
    if not db.query(models.Customer).filter_by(id=customer_id).first():
        raise HTTPException(404, "Customer not found")
    return db.query(models.ChargingSession).filter_by(customer_id=customer_id).all()
