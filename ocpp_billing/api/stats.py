from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
import models

router = APIRouter()


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    now = _utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    online_threshold = now - timedelta(minutes=2)

    today_rows = (
        db.query(models.ChargingSession)
        .filter(models.ChargingSession.start_time >= today_start)
        .all()
    )
    active_count = db.query(models.ChargingSession).filter_by(status="active").count()
    online_stations = (
        db.query(models.ChargePoint)
        .filter(models.ChargePoint.last_heartbeat >= online_threshold)
        .count()
    )
    total_rev = (
        db.query(func.sum(models.ChargingSession.total_cost))
        .filter_by(status="completed")
        .scalar()
        or 0.0
    )

    return {
        "today_sessions": len(today_rows),
        "today_revenue": round(sum(s.total_cost for s in today_rows), 2),
        "today_energy_kwh": round(sum(s.energy_kwh for s in today_rows), 2),
        "active_sessions": active_count,
        "online_stations": online_stations,
        "total_customers": db.query(models.Customer).count(),
        "total_cards": db.query(models.Card).count(),
        "total_stations": db.query(models.ChargePoint).count(),
        "total_sessions": db.query(models.ChargingSession).count(),
        "total_revenue": round(total_rev, 2),
    }


@router.get("/daily")
def daily_stats(days: int = 30, db: Session = Depends(get_db)):
    start_date = _utcnow().date() - timedelta(days=days - 1)
    start_dt = datetime.combine(start_date, datetime.min.time())

    rows = (
        db.query(models.ChargingSession)
        .filter(
            models.ChargingSession.start_time >= start_dt,
            models.ChargingSession.status == "completed",
        )
        .all()
    )

    daily: dict = {}
    for s in rows:
        if not s.start_time:
            continue
        d = s.start_time.date().isoformat()
        if d not in daily:
            daily[d] = {"date": d, "sessions": 0, "revenue": 0.0,
                        "energy_kwh": 0.0, "blocking_fee": 0.0}
        daily[d]["sessions"] += 1
        daily[d]["revenue"] = round(daily[d]["revenue"] + s.total_cost, 2)
        daily[d]["energy_kwh"] = round(daily[d]["energy_kwh"] + s.energy_kwh, 4)
        daily[d]["blocking_fee"] = round(daily[d]["blocking_fee"] + s.cost_blocking, 4)

    result = []
    from datetime import date as date_cls, timedelta as td
    for i in range(days):
        d = (start_date + td(days=i)).isoformat()
        result.append(daily.get(d, {
            "date": d, "sessions": 0, "revenue": 0.0,
            "energy_kwh": 0.0, "blocking_fee": 0.0,
        }))
    return result
