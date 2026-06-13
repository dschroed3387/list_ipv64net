"""
Async CDR push to eMSP.

Called via asyncio.create_task() after a roaming session completes so the
OCPP StopTransaction response is not delayed.
"""

import logging
from datetime import datetime, timezone

import httpx

from database import SessionLocal
import models

logger = logging.getLogger("ocpi.cdr_push")

OUR_COUNTRY_CODE = "DE"
OUR_PARTY_ID = "OCP"


def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dt_str(dt: datetime | None) -> str:
    if not dt:
        return _utcnow_str()
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_cdr_payload(cdr: models.OcpiCdr, party: models.OcpiParty) -> dict:
    """Construct an OCPI 2.2.1 CDR payload from the database record."""
    session = cdr.session
    charging_periods = []

    if session:
        if session.cost_connection > 0:
            charging_periods.append({
                "start_date_time": _dt_str(session.start_time),
                "dimensions": [{"type": "FLAT", "volume": 1.0, "price": session.cost_connection}],
            })
        if session.energy_kwh > 0:
            charging_periods.append({
                "start_date_time": _dt_str(session.start_time),
                "dimensions": [{"type": "ENERGY", "volume": session.energy_kwh, "price": session.cost_energy}],
            })
        if session.cost_time > 0:
            charging_periods.append({
                "start_date_time": _dt_str(session.start_time),
                "dimensions": [{"type": "TIME", "volume": round(session.charging_minutes / 60, 4), "price": session.cost_time}],
            })
        if session.cost_blocking > 0:
            charging_periods.append({
                "start_date_time": _dt_str(session.charging_stopped_at or session.end_time),
                "dimensions": [{"type": "PARKING_TIME", "volume": round(session.blocking_minutes / 60, 4), "price": session.cost_blocking}],
            })

    return {
        "country_code": OUR_COUNTRY_CODE,
        "party_id": OUR_PARTY_ID,
        "id": cdr.cdr_id,
        "start_date_time": _dt_str(cdr.start_date_time),
        "end_date_time": _dt_str(cdr.end_date_time),
        "session_id": str(cdr.session_db_id),
        "cdr_token": {
            "country_code": party.country_code,
            "party_id": party.party_id,
            "uid": cdr.token_uid or "",
            "type": "RFID",
            "contract_id": cdr.contract_id or "",
        },
        "auth_method": "AUTH_REQUEST",
        "cdr_location": {
            "id": f"loc-{cdr.session_db_id}",
            "name": cdr.charge_point_ocpp_id or "Unknown Station",
            "address": "–",
            "city": "–",
            "country": OUR_COUNTRY_CODE,
            "evse_uid": f"evse-{cdr.session_db_id}",
            "connector_id": "1",
            "connector_standard": "IEC_62196_T2",
            "connector_format": "SOCKET",
            "connector_power_type": "AC_3_PHASE",
        },
        "currency": cdr.currency,
        "charging_periods": charging_periods,
        "total_cost": {"excl_vat": round(cdr.total_cost, 2)},
        "total_energy": round(cdr.total_energy, 4),
        "total_time": round(cdr.total_time_hours, 4),
        "last_updated": _utcnow_str(),
    }


async def push_cdr(cdr_id: int) -> None:
    """Push a single CDR to the eMSP. Updates status in DB."""
    db = SessionLocal()
    try:
        cdr = db.query(models.OcpiCdr).filter_by(id=cdr_id).first()
        if not cdr:
            return

        party = cdr.party
        if not party or not party.their_token:
            cdr.status = "FAILED"
            cdr.error_message = "eMSP token not configured"
            db.commit()
            return

        # Resolve CDR push URL: use cached URL or fall back to versions discovery
        target_url = party.their_cdrs_url
        if not target_url and party.their_versions_url:
            target_url = await _discover_cdr_url(party.their_versions_url, party.their_token)
            if target_url:
                party.their_cdrs_url = target_url
                db.commit()

        if not target_url:
            cdr.status = "FAILED"
            cdr.error_message = "Cannot determine eMSP CDR endpoint"
            cdr.push_attempts += 1
            db.commit()
            return

        payload = build_cdr_payload(cdr, party)

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                target_url,
                json=payload,
                headers={
                    "Authorization": f"Token {party.their_token}",
                    "Content-Type": "application/json",
                    "X-Request-ID": cdr.cdr_id,
                },
            )

        cdr.push_attempts += 1
        if resp.status_code in (200, 201):
            cdr.status = "SENT"
            cdr.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
            logger.info("CDR %s pushed to %s %s (HTTP %d)", cdr.cdr_id, party.country_code, party.party_id, resp.status_code)
        else:
            cdr.status = "FAILED"
            cdr.error_message = f"HTTP {resp.status_code}: {resp.text[:300]}"
            logger.warning("CDR push failed for %s: %s", cdr.cdr_id, cdr.error_message)

        db.commit()

    except Exception as exc:
        logger.exception("CDR push exception for cdr_id=%d: %s", cdr_id, exc)
        try:
            cdr.status = "FAILED"
            cdr.error_message = str(exc)[:500]
            cdr.push_attempts += 1
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


async def _discover_cdr_url(versions_url: str, token: str) -> str | None:
    """Call eMSP versions endpoint to discover their CDR module URL."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Get versions
            r = await client.get(versions_url, headers={"Authorization": f"Token {token}"})
            if r.status_code != 200:
                return None
            versions = r.json().get("data", [])
            v22 = next((v for v in versions if v.get("version") == "2.2"), None)
            v221 = next((v for v in versions if v.get("version") == "2.2.1"), None)
            details_url = (v221 or v22 or {}).get("url")
            if not details_url:
                return None

            # Get version details
            r2 = await client.get(details_url, headers={"Authorization": f"Token {token}"})
            if r2.status_code != 200:
                return None
            modules = r2.json().get("data", {}).get("endpoints", [])
            cdr_module = next((m for m in modules if m.get("identifier") == "cdrs"), None)
            return cdr_module.get("url") if cdr_module else None
    except Exception:
        return None
