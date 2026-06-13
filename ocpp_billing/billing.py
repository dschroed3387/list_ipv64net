"""
Billing engine: calculates cost breakdown for a completed charging session.

Cost components:
  1. Connection fee  – flat € per session start
  2. Energy cost     – €/kWh * kWh consumed
  3. Time cost       – €/min * minutes actively charging
  4. Blocking fee    – €/min * max(0, idle_minutes - grace_period)
                       (Blockiergebühr: charged after EV stops drawing power
                        but remains plugged in beyond the grace period)
"""

from datetime import datetime
from dataclasses import dataclass


@dataclass
class BillingResult:
    energy_kwh: float
    duration_minutes: float
    charging_minutes: float
    blocking_minutes: float   # chargeable blocking time (after grace period)
    cost_energy: float
    cost_time: float
    cost_connection: float
    cost_blocking: float
    total_cost: float


def calculate_cost(
    meter_start_wh: float,
    meter_stop_wh: float,
    session_start: datetime,
    session_end: datetime,
    charging_stopped_at: datetime | None,
    price_per_kwh: float,
    price_per_minute: float,
    connection_fee: float,
    blocking_fee_per_minute: float,
    blocking_grace_period_minutes: int,
) -> BillingResult:
    energy_kwh = max(0.0, (meter_stop_wh - meter_start_wh) / 1000.0)

    total_seconds = (session_end - session_start).total_seconds()
    duration_minutes = max(0.0, total_seconds / 60.0)

    charging_end = charging_stopped_at if charging_stopped_at else session_end
    charging_seconds = (charging_end - session_start).total_seconds()
    charging_minutes = max(0.0, charging_seconds / 60.0)

    idle_minutes = max(0.0, duration_minutes - charging_minutes)
    blocking_minutes = max(0.0, idle_minutes - blocking_grace_period_minutes)

    cost_energy = round(energy_kwh * price_per_kwh, 4)
    cost_time = round(charging_minutes * price_per_minute, 4)
    cost_connection = round(connection_fee, 4)
    cost_blocking = round(blocking_minutes * blocking_fee_per_minute, 4)
    total_cost = round(cost_energy + cost_time + cost_connection + cost_blocking, 2)

    return BillingResult(
        energy_kwh=round(energy_kwh, 4),
        duration_minutes=round(duration_minutes, 2),
        charging_minutes=round(charging_minutes, 2),
        blocking_minutes=round(blocking_minutes, 2),
        cost_energy=cost_energy,
        cost_time=cost_time,
        cost_connection=cost_connection,
        cost_blocking=cost_blocking,
        total_cost=total_cost,
    )


def resolve_tariff_period(tariff, session_start: datetime):
    """
    Return the highest-priority TariffPeriod matching session_start, or None.
    weekdays: comma-separated 0=Mon…6=Sun; empty means every day.
    hour_from/to: inclusive hour range (handles overnight wrap, e.g. 22–6).
    """
    if not tariff or not tariff.periods:
        return None

    weekday = session_start.weekday()
    hour = session_start.hour

    matching = []
    for period in tariff.periods:
        if period.weekdays:
            try:
                allowed = {int(d.strip()) for d in period.weekdays.split(",") if d.strip()}
            except ValueError:
                continue
            if weekday not in allowed:
                continue

        if period.hour_from <= period.hour_to:
            in_range = period.hour_from <= hour <= period.hour_to
        else:
            in_range = hour >= period.hour_from or hour <= period.hour_to

        if in_range:
            matching.append(period)

    return max(matching, key=lambda p: p.priority) if matching else None


def vat_breakdown(gross: float, vat_rate: float) -> tuple[float, float, float]:
    """Return (net, vat_amount, gross) given a gross amount and VAT rate."""
    net = round(gross / (1 + vat_rate), 2)
    vat_amount = round(gross - net, 2)
    return net, vat_amount, round(gross, 2)
