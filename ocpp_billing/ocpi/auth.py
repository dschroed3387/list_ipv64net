"""OCPI token authentication dependency for FastAPI endpoints."""

from fastapi import Request, HTTPException
from database import SessionLocal
import models


def get_ocpi_party(request: Request) -> models.OcpiParty:
    """Extract and validate OCPI Bearer token, return the matching party."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Token "):
        raise HTTPException(status_code=401, detail="Missing or malformed OCPI token")
    token = auth[6:].strip()
    db = SessionLocal()
    try:
        party = db.query(models.OcpiParty).filter_by(our_token=token).first()
        if not party:
            raise HTTPException(status_code=401, detail="Invalid OCPI token")
        if party.status == "SUSPENDED":
            raise HTTPException(status_code=403, detail="Party is suspended")
        return party
    finally:
        db.close()
