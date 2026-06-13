from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
import models
import schemas

router = APIRouter()


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("/live")
def live_status(db: Session = Depends(get_db)):
    """All charge points with online flag and active session summary."""
    now = _utcnow()
    cps = db.query(models.ChargePoint).all()
    result = []
    for cp in cps:
        active = (
            db.query(models.ChargingSession)
            .filter_by(charge_point_db_id=cp.id, status="active")
            .first()
        )
        is_online = (
            cp.last_heartbeat is not None
            and (now - cp.last_heartbeat).total_seconds() < 120
        )
        energy_so_far = round(
            max(0, (active.meter_stop - active.meter_start) / 1000) if active else 0, 3
        )
        result.append({
            "id": cp.id,
            "charge_point_id": cp.charge_point_id,
            "vendor": cp.vendor,
            "model": cp.model,
            "status": cp.status,
            "last_heartbeat": cp.last_heartbeat.isoformat() if cp.last_heartbeat else None,
            "is_online": is_online,
            "active_session": {
                "id": active.id,
                "transaction_id": active.transaction_id,
                "start_time": active.start_time.isoformat() if active.start_time else None,
                "energy_kwh": energy_so_far,
                "customer_id": active.customer_id,
                "connector_id": active.connector_id,
            } if active else None,
        })
    return result


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


@router.post("/{charge_point_id}/remote-start")
async def remote_start(
    charge_point_id: str,
    connector_id: int = 1,
    id_tag: str = "REMOTE",
    db: Session = Depends(get_db),
):
    """Send RemoteStartTransaction to a connected charge point."""
    import connection_registry
    from ocpp.v16 import call as ocpp_call

    cp_handler = connection_registry.get(charge_point_id)
    if not cp_handler:
        raise HTTPException(503, f"Charge point '{charge_point_id}' is not connected")

    try:
        req = ocpp_call.RemoteStartTransaction(connector_id=connector_id, id_tag=id_tag)
        result = await cp_handler.call(req)
        return {"status": result.status, "charge_point_id": charge_point_id}
    except Exception as e:
        raise HTTPException(500, f"Remote start failed: {e}")


@router.post("/{charge_point_id}/remote-stop")
async def remote_stop(charge_point_id: str, transaction_id: int, db: Session = Depends(get_db)):
    """Send RemoteStopTransaction to a connected charge point."""
    import connection_registry
    from ocpp.v16 import call as ocpp_call

    cp_handler = connection_registry.get(charge_point_id)
    if not cp_handler:
        raise HTTPException(503, f"Charge point '{charge_point_id}' is not connected")

    try:
        req = ocpp_call.RemoteStopTransaction(transaction_id=transaction_id)
        result = await cp_handler.call(req)
        return {"status": result.status, "charge_point_id": charge_point_id}
    except Exception as e:
        raise HTTPException(500, f"Remote stop failed: {e}")
