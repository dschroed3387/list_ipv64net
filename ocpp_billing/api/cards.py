from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
import models
import schemas

router = APIRouter()


@router.post("/", response_model=schemas.CardOut, status_code=201)
def create_card(body: schemas.CardCreate, db: Session = Depends(get_db)):
    if not db.query(models.Customer).filter_by(id=body.customer_id).first():
        raise HTTPException(404, "Customer not found")
    if db.query(models.Card).filter_by(rfid_tag=body.rfid_tag).first():
        raise HTTPException(409, "RFID tag already registered")
    card = models.Card(**body.model_dump())
    db.add(card)
    db.commit()
    db.refresh(card)
    return card


@router.get("/", response_model=list[schemas.CardOut])
def list_cards(db: Session = Depends(get_db)):
    return db.query(models.Card).all()


@router.get("/{card_id}", response_model=schemas.CardOut)
def get_card(card_id: int, db: Session = Depends(get_db)):
    card = db.query(models.Card).filter_by(id=card_id).first()
    if not card:
        raise HTTPException(404, "Card not found")
    return card


@router.put("/{card_id}", response_model=schemas.CardOut)
def update_card(card_id: int, body: schemas.CardUpdate, db: Session = Depends(get_db)):
    card = db.query(models.Card).filter_by(id=card_id).first()
    if not card:
        raise HTTPException(404, "Card not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(card, field, value)
    db.commit()
    db.refresh(card)
    return card


@router.delete("/{card_id}", status_code=204)
def delete_card(card_id: int, db: Session = Depends(get_db)):
    card = db.query(models.Card).filter_by(id=card_id).first()
    if not card:
        raise HTTPException(404, "Card not found")
    db.delete(card)
    db.commit()


@router.post("/{card_id}/balance", response_model=schemas.CardOut)
def add_balance(card_id: int, body: schemas.CardBalanceAdd, db: Session = Depends(get_db)):
    """Add prepaid balance to a card (Guthaben aufladen)."""
    card = db.query(models.Card).filter_by(id=card_id).first()
    if not card:
        raise HTTPException(404, "Card not found")
    card.balance = round(card.balance + body.amount, 2)
    db.commit()
    db.refresh(card)
    return card
