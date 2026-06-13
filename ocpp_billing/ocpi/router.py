"""
OCPI 2.2.1 Router – CPO role.

Standard OCPI endpoints (called by eMSPs):
  /ocpi/versions
  /ocpi/2.2/details
  /ocpi/2.2/credentials   GET / POST / DELETE
  /ocpi/2.2/tokens        PUT / PATCH / DELETE / GET (eMSP pushes Fremdkarten)
  /ocpi/2.2/locations     GET
  /ocpi/2.2/cdrs          GET
  /ocpi/2.2/sessions      GET

Admin endpoints (called by our own dashboard at /api/ocpi/...):
  parties  GET / POST / PUT / DELETE
  tokens   GET / DELETE
  cdrs     GET + manual push
  stats    GET
"""

import asyncio
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
import models
from ocpi.auth import get_ocpi_party
from ocpi.schemas import (
    CredentialsIn, CredentialsOut, CredentialsRole, BusinessDetails,
    OcpiTokenIn, PartyCreate, PartyUpdate, PartyOut,
    OcpiTokenAdminOut, OcpiCdrAdminOut,
)

OUR_COUNTRY_CODE = "DE"
OUR_PARTY_ID = "OCP"
OUR_NAME = "OCPP Billing CPO"
OUR_WEBSITE = "http://localhost:8000"

standard = APIRouter()   # mounted at /ocpi
admin = APIRouter()      # mounted at /api/ocpi


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ocpi_ok(data: Any) -> dict:
    return {"data": data, "status_code": 1000, "status_message": "Success", "timestamp": _utcnow_str()}


def _ocpi_err(code: int, msg: str) -> dict:
    return {"data": None, "status_code": code, "status_message": msg, "timestamp": _utcnow_str()}


# ── Versions ──────────────────────────────────────────────────────────────────

@standard.get("/versions")
def get_versions(request: Request):
    base = str(request.base_url).rstrip("/")
    return _ocpi_ok([
        {"version": "2.2",   "url": f"{base}/ocpi/2.2/details"},
        {"version": "2.2.1", "url": f"{base}/ocpi/2.2/details"},
    ])


@standard.get("/2.2/details")
def get_version_details(request: Request):
    base = str(request.base_url).rstrip("/")
    endpoints = [
        {"identifier": "credentials",  "role": "SENDER", "url": f"{base}/ocpi/2.2/credentials"},
        {"identifier": "locations",    "role": "SENDER", "url": f"{base}/ocpi/2.2/locations"},
        {"identifier": "tokens",       "role": "RECEIVER", "url": f"{base}/ocpi/2.2/tokens"},
        {"identifier": "sessions",     "role": "SENDER", "url": f"{base}/ocpi/2.2/sessions"},
        {"identifier": "cdrs",         "role": "SENDER", "url": f"{base}/ocpi/2.2/cdrs"},
    ]
    return _ocpi_ok({"version": "2.2.1", "endpoints": endpoints})


# ── Credentials ───────────────────────────────────────────────────────────────

@standard.get("/2.2/credentials")
def get_credentials(request: Request, party: models.OcpiParty = Depends(get_ocpi_party)):
    base = str(request.base_url).rstrip("/")
    return _ocpi_ok(CredentialsOut(
        token=party.our_token,
        url=f"{base}/ocpi/versions",
        roles=[CredentialsRole(
            role="CPO",
            business_details=BusinessDetails(name=OUR_NAME, website=OUR_WEBSITE),
            country_code=OUR_COUNTRY_CODE,
            party_id=OUR_PARTY_ID,
        )],
    ).model_dump())


@standard.post("/2.2/credentials")
def register_credentials(
    body: CredentialsIn,
    request: Request,
    party: models.OcpiParty = Depends(get_ocpi_party),
    db: Session = Depends(get_db),
):
    """eMSP completes the OCPI handshake: sends their token + URL."""
    party.their_token = body.token
    party.their_versions_url = body.url
    party.their_cdrs_url = None   # will be re-discovered on next CDR push
    party.status = "CONNECTED"
    party.last_updated = _utcnow()
    if body.roles:
        r = body.roles[0]
        party.country_code = r.country_code
        party.party_id = r.party_id
        party.role = r.role
        party.name = r.business_details.name
        party.website = r.business_details.website
    db.commit()

    base = str(request.base_url).rstrip("/")
    return _ocpi_ok(CredentialsOut(
        token=party.our_token,
        url=f"{base}/ocpi/versions",
        roles=[CredentialsRole(
            role="CPO",
            business_details=BusinessDetails(name=OUR_NAME, website=OUR_WEBSITE),
            country_code=OUR_COUNTRY_CODE,
            party_id=OUR_PARTY_ID,
        )],
    ).model_dump())


@standard.delete("/2.2/credentials")
def deregister_credentials(
    party: models.OcpiParty = Depends(get_ocpi_party),
    db: Session = Depends(get_db),
):
    party.status = "SUSPENDED"
    party.their_token = None
    party.last_updated = _utcnow()
    db.commit()
    return _ocpi_ok(None)


# ── Tokens (RECEIVER) – eMSP pushes Fremdkarten to us ────────────────────────

@standard.put("/2.2/tokens/{country_code}/{party_id}/{token_uid}")
def push_token(
    country_code: str,
    party_id: str,
    token_uid: str,
    body: OcpiTokenIn,
    party: models.OcpiParty = Depends(get_ocpi_party),
    db: Session = Depends(get_db),
):
    """eMSP pushes/updates a single token (Fremdkarte)."""
    token = db.query(models.OcpiToken).filter_by(uid=token_uid).first()
    if token and token.party_id_ref != party.id:
        raise HTTPException(403, "Token belongs to another party")

    if not token:
        token = models.OcpiToken(uid=token_uid, party_id_ref=party.id)
        db.add(token)

    token.type = body.type
    token.contract_id = body.contract_id
    token.visual_number = body.visual_number
    token.issuer = body.issuer
    token.group_id = body.group_id
    token.valid = body.valid
    token.whitelist = body.whitelist
    token.last_updated = _utcnow()
    db.commit()
    return _ocpi_ok(None)


@standard.patch("/2.2/tokens/{country_code}/{party_id}/{token_uid}")
def patch_token(
    country_code: str,
    party_id: str,
    token_uid: str,
    body: dict,
    party: models.OcpiParty = Depends(get_ocpi_party),
    db: Session = Depends(get_db),
):
    token = db.query(models.OcpiToken).filter_by(uid=token_uid, party_id_ref=party.id).first()
    if not token:
        return _ocpi_err(2003, "Token not found"), 404
    for field in ("valid", "whitelist", "visual_number", "group_id"):
        if field in body:
            setattr(token, field, body[field])
    token.last_updated = _utcnow()
    db.commit()
    return _ocpi_ok(None)


@standard.delete("/2.2/tokens/{country_code}/{party_id}/{token_uid}")
def delete_token(
    country_code: str,
    party_id: str,
    token_uid: str,
    party: models.OcpiParty = Depends(get_ocpi_party),
    db: Session = Depends(get_db),
):
    token = db.query(models.OcpiToken).filter_by(uid=token_uid, party_id_ref=party.id).first()
    if token:
        db.delete(token)
        db.commit()
    return _ocpi_ok(None)


@standard.get("/2.2/tokens")
def get_tokens(
    party: models.OcpiParty = Depends(get_ocpi_party),
    db: Session = Depends(get_db),
    date_from: str | None = None,
    offset: int = 0,
    limit: int = 100,
):
    """Return tokens belonging to the calling party (pull model)."""
    q = db.query(models.OcpiToken).filter_by(party_id_ref=party.id)
    tokens = q.offset(offset).limit(limit).all()
    data = [
        {
            "country_code": party.country_code,
            "party_id": party.party_id,
            "uid": t.uid,
            "type": t.type,
            "contract_id": t.contract_id,
            "visual_number": t.visual_number,
            "issuer": t.issuer,
            "group_id": t.group_id,
            "valid": t.valid,
            "whitelist": t.whitelist,
            "last_updated": t.last_updated.isoformat() if t.last_updated else _utcnow_str(),
        }
        for t in tokens
    ]
    return _ocpi_ok(data)


# ── Locations (SENDER) – expose our charge points ────────────────────────────

@standard.get("/2.2/locations")
def get_locations(
    party: models.OcpiParty = Depends(get_ocpi_party),
    db: Session = Depends(get_db),
    offset: int = 0,
    limit: int = 100,
):
    cps = db.query(models.ChargePoint).offset(offset).limit(limit).all()
    locs = []
    for cp in cps:
        locs.append({
            "country_code": OUR_COUNTRY_CODE,
            "party_id": OUR_PARTY_ID,
            "id": f"loc-{cp.id}",
            "publish": True,
            "name": cp.charge_point_id,
            "address": "–",
            "city": "–",
            "country": OUR_COUNTRY_CODE,
            "evses": [{
                "uid": f"evse-{cp.id}",
                "status": _map_cp_status(cp.status),
                "connectors": [{
                    "id": "1",
                    "standard": "IEC_62196_T2",
                    "format": "SOCKET",
                    "power_type": "AC_3_PHASE",
                    "max_voltage": 400,
                    "max_amperage": 32,
                    "last_updated": cp.last_heartbeat.isoformat() if cp.last_heartbeat else _utcnow_str(),
                }],
                "last_updated": cp.last_heartbeat.isoformat() if cp.last_heartbeat else _utcnow_str(),
            }],
            "last_updated": cp.last_heartbeat.isoformat() if cp.last_heartbeat else _utcnow_str(),
        })
    return _ocpi_ok(locs)


def _map_cp_status(status: str) -> str:
    return {
        "Available": "AVAILABLE",
        "Charging": "CHARGING",
        "Faulted": "INOPERATIVE",
        "Unavailable": "INOPERATIVE",
        "Reserved": "RESERVED",
        "Finishing": "FINISHING",
    }.get(status, "UNKNOWN")


# ── CDRs (SENDER) – eMSP can pull completed CDRs ─────────────────────────────

@standard.get("/2.2/cdrs")
def get_cdrs(
    party: models.OcpiParty = Depends(get_ocpi_party),
    db: Session = Depends(get_db),
    date_from: str | None = None,
    offset: int = 0,
    limit: int = 50,
):
    q = db.query(models.OcpiCdr).filter_by(party_id_ref=party.id)
    cdrs = q.order_by(models.OcpiCdr.id.desc()).offset(offset).limit(limit).all()
    from ocpi.cdr_push import build_cdr_payload
    data = [build_cdr_payload(c, party) for c in cdrs]
    return _ocpi_ok(data)


# ── Sessions (SENDER) ─────────────────────────────────────────────────────────

@standard.get("/2.2/sessions")
def get_sessions(
    party: models.OcpiParty = Depends(get_ocpi_party),
    db: Session = Depends(get_db),
    offset: int = 0,
    limit: int = 50,
):
    active = (
        db.query(models.ChargingSession)
        .join(models.OcpiToken, models.ChargingSession.ocpi_token_id == models.OcpiToken.id, isouter=True)
        .filter(
            models.ChargingSession.status == "active",
            models.OcpiToken.party_id_ref == party.id,
        )
        .offset(offset).limit(limit).all()
    )
    data = []
    for s in active:
        tok = s.ocpi_token
        cp = s.charge_point
        data.append({
            "country_code": OUR_COUNTRY_CODE,
            "party_id": OUR_PARTY_ID,
            "id": str(s.id),
            "start_date_time": s.start_time.isoformat() + "Z" if s.start_time else _utcnow_str(),
            "kwh": s.energy_kwh,
            "cdr_token": {
                "country_code": party.country_code,
                "party_id": party.party_id,
                "uid": tok.uid if tok else "",
                "type": tok.type if tok else "RFID",
                "contract_id": tok.contract_id or "" if tok else "",
            },
            "auth_method": "AUTH_REQUEST",
            "location_id": f"loc-{cp.id}" if cp else "–",
            "evse_uid": f"evse-{cp.id}" if cp else "–",
            "connector_id": str(s.connector_id),
            "currency": "EUR",
            "status": "ACTIVE",
            "last_updated": _utcnow_str(),
        })
    return _ocpi_ok(data)


# ═══════════════════════════════════════════════════════════════════════════════
# Admin endpoints (/api/ocpi/...)
# ═══════════════════════════════════════════════════════════════════════════════

@admin.get("/parties", response_model=list[PartyOut])
def list_parties(db: Session = Depends(get_db)):
    parties = db.query(models.OcpiParty).all()
    result = []
    for p in parties:
        out = PartyOut.model_validate(p)
        out.token_count = len(p.tokens)
        out.cdr_count = len(p.cdrs)
        result.append(out)
    return result


@admin.get("/parties/generate-token")
def generate_token():
    """Generate a cryptographically random OCPI token to assign to a new party."""
    return {"token": secrets.token_urlsafe(32)}


@admin.post("/parties", response_model=PartyOut, status_code=201)
def create_party(body: PartyCreate, db: Session = Depends(get_db)):
    if db.query(models.OcpiParty).filter_by(our_token=body.our_token).first():
        raise HTTPException(409, "Token already in use")
    party = models.OcpiParty(**body.model_dump())
    db.add(party)
    db.commit()
    db.refresh(party)
    out = PartyOut.model_validate(party)
    out.token_count = 0
    out.cdr_count = 0
    return out


@admin.put("/parties/{party_id}", response_model=PartyOut)
def update_party(party_id: int, body: PartyUpdate, db: Session = Depends(get_db)):
    party = db.query(models.OcpiParty).filter_by(id=party_id).first()
    if not party:
        raise HTTPException(404, "Party not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(party, k, v)
    party.last_updated = _utcnow()
    db.commit()
    db.refresh(party)
    out = PartyOut.model_validate(party)
    out.token_count = len(party.tokens)
    out.cdr_count = len(party.cdrs)
    return out


@admin.delete("/parties/{party_id}", status_code=204)
def delete_party(party_id: int, db: Session = Depends(get_db)):
    party = db.query(models.OcpiParty).filter_by(id=party_id).first()
    if not party:
        raise HTTPException(404, "Party not found")
    db.delete(party)
    db.commit()


@admin.get("/tokens", response_model=list[OcpiTokenAdminOut])
def list_tokens(
    party_id: int | None = None,
    valid: bool | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.OcpiToken)
    if party_id:
        q = q.filter_by(party_id_ref=party_id)
    if valid is not None:
        q = q.filter_by(valid=valid)
    return q.order_by(models.OcpiToken.id.desc()).all()


@admin.delete("/tokens/{token_id}", status_code=204)
def delete_ocpi_token(token_id: int, db: Session = Depends(get_db)):
    t = db.query(models.OcpiToken).filter_by(id=token_id).first()
    if not t:
        raise HTTPException(404, "Token not found")
    db.delete(t)
    db.commit()


@admin.get("/cdrs", response_model=list[OcpiCdrAdminOut])
def list_cdrs(
    status: str | None = None,
    party_id: int | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.OcpiCdr)
    if status:
        q = q.filter_by(status=status)
    if party_id:
        q = q.filter_by(party_id_ref=party_id)
    return q.order_by(models.OcpiCdr.id.desc()).all()


@admin.post("/cdrs/{cdr_id}/push")
async def push_cdr_manually(cdr_id: int, db: Session = Depends(get_db)):
    """Manually trigger pushing a CDR to the eMSP."""
    cdr = db.query(models.OcpiCdr).filter_by(id=cdr_id).first()
    if not cdr:
        raise HTTPException(404, "CDR not found")
    from ocpi.cdr_push import push_cdr
    asyncio.create_task(push_cdr(cdr_id))
    return {"message": f"CDR {cdr_id} push triggered"}


@admin.get("/stats")
def ocpi_stats(db: Session = Depends(get_db)):
    now = _utcnow()
    total_tokens = db.query(models.OcpiToken).count()
    valid_tokens = db.query(models.OcpiToken).filter_by(valid=True).count()
    pending_cdrs = db.query(models.OcpiCdr).filter_by(status="PENDING").count()
    failed_cdrs = db.query(models.OcpiCdr).filter_by(status="FAILED").count()
    sent_cdrs = db.query(models.OcpiCdr).filter_by(status="SENT").count()
    parties = db.query(models.OcpiParty).count()
    connected = db.query(models.OcpiParty).filter_by(status="CONNECTED").count()
    return {
        "parties": parties,
        "connected_parties": connected,
        "total_tokens": total_tokens,
        "valid_tokens": valid_tokens,
        "pending_cdrs": pending_cdrs,
        "failed_cdrs": failed_cdrs,
        "sent_cdrs": sent_cdrs,
    }
