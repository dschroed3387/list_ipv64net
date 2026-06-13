"""
OCPP 1.6 charge point handler.

Each connecting charge point gets its own ChargePoint16 instance.
Authorize checks local cards first, then OCPI tokens (Fremdkarten).
StopTransaction creates an OcpiCdr for roaming sessions and pushes it async.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import WebSocket
from ocpp.routing import on
from ocpp.v16 import ChargePoint as OcppCp, call_result
from ocpp.v16.enums import (
    Action,
    AuthorizationStatus,
    ChargePointStatus,
    RegistrationStatus,
)

from billing import calculate_cost
from database import SessionLocal
import models

logger = logging.getLogger("ocpp")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


class _StarletteAdapter:
    def __init__(self, ws: WebSocket):
        self._ws = ws

    async def recv(self) -> str:
        return await self._ws.receive_text()

    async def send(self, data: str) -> None:
        await self._ws.send_text(data)


class ChargePoint16(OcppCp):

    def __init__(self, cp_id: str, ws: WebSocket):
        super().__init__(cp_id, _StarletteAdapter(ws))
        self._db_cp_id: int | None = None

    def _get_db(self):
        return SessionLocal()

    def _resolve_tariff(self, db, customer_id: int | None):
        if customer_id:
            customer = db.query(models.Customer).filter_by(id=customer_id).first()
            if customer and customer.tariff:
                return customer.tariff
        return db.query(models.Tariff).filter_by(is_default=True).first()

    # ── BootNotification ─────────────────────────────────────────────────────

    @on(Action.BootNotification)
    async def on_boot_notification(
        self,
        charge_point_model: str,
        charge_point_vendor: str,
        charge_point_serial_number: str = "",
        firmware_version: str = "",
        **kwargs,
    ):
        db = self._get_db()
        try:
            cp = db.query(models.ChargePoint).filter_by(charge_point_id=self.id).first()
            if not cp:
                cp = models.ChargePoint(charge_point_id=self.id)
                db.add(cp)
            cp.vendor = charge_point_vendor
            cp.model = charge_point_model
            cp.serial_number = charge_point_serial_number
            cp.firmware_version = firmware_version
            cp.status = "Available"
            cp.last_heartbeat = _utcnow()
            db.commit()
            db.refresh(cp)
            self._db_cp_id = cp.id
            logger.info("BootNotification from %s (%s %s)", self.id, charge_point_vendor, charge_point_model)
        finally:
            db.close()

        return call_result.BootNotification(
            current_time=_utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            interval=60,
            status=RegistrationStatus.accepted,
        )

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    @on(Action.Heartbeat)
    async def on_heartbeat(self, **kwargs):
        db = self._get_db()
        try:
            if self._db_cp_id:
                cp = db.query(models.ChargePoint).filter_by(id=self._db_cp_id).first()
                if cp:
                    cp.last_heartbeat = _utcnow()
                    db.commit()
        finally:
            db.close()
        return call_result.Heartbeat(current_time=_utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))

    # ── StatusNotification ────────────────────────────────────────────────────

    @on(Action.StatusNotification)
    async def on_status_notification(
        self,
        connector_id: int,
        error_code: str,
        status: str,
        timestamp: str = "",
        **kwargs,
    ):
        db = self._get_db()
        try:
            if self._db_cp_id:
                cp = db.query(models.ChargePoint).filter_by(id=self._db_cp_id).first()
                if cp:
                    cp.status = status
                    db.commit()

            finishing_statuses = {
                ChargePointStatus.finishing,
                ChargePointStatus.suspended_ev,
                ChargePointStatus.suspended_evse,
            }
            if status in finishing_statuses and connector_id > 0:
                event_time = _parse_dt(timestamp) or _utcnow()
                session = (
                    db.query(models.ChargingSession)
                    .filter_by(charge_point_db_id=self._db_cp_id, connector_id=connector_id, status="active")
                    .first()
                )
                if session and not session.charging_stopped_at:
                    session.charging_stopped_at = event_time
                    db.commit()
                    logger.info("Charging stopped on %s connector %d at %s", self.id, connector_id, event_time)
        finally:
            db.close()
        return call_result.StatusNotification()

    # ── Authorize ─────────────────────────────────────────────────────────────

    @on(Action.Authorize)
    async def on_authorize(self, id_tag: str, **kwargs):
        db = self._get_db()
        try:
            # 1. Check local card
            card = db.query(models.Card).filter_by(rfid_tag=id_tag, is_active=True).first()
            if card:
                logger.info("Authorized local card %s for customer_id=%d", id_tag, card.customer_id)
                return call_result.Authorize(id_tag_info={"status": AuthorizationStatus.accepted})

            # 2. Check OCPI token (Fremdkarte)
            ocpi_tok = db.query(models.OcpiToken).filter_by(uid=id_tag, valid=True).first()
            if ocpi_tok:
                party = ocpi_tok.party
                logger.info("Authorized OCPI token %s from party %s/%s", id_tag, party.country_code, party.party_id)
                return call_result.Authorize(id_tag_info={"status": AuthorizationStatus.accepted})

            logger.warning("Authorization rejected: unknown/inactive tag %s", id_tag)
            return call_result.Authorize(id_tag_info={"status": AuthorizationStatus.invalid})
        finally:
            db.close()

    # ── StartTransaction ──────────────────────────────────────────────────────

    @on(Action.StartTransaction)
    async def on_start_transaction(
        self,
        connector_id: int,
        id_tag: str,
        meter_start: int,
        timestamp: str,
        reservation_id: int = 0,
        **kwargs,
    ):
        db = self._get_db()
        try:
            start_time = _parse_dt(timestamp) or _utcnow()

            # 1. Try local card
            card = db.query(models.Card).filter_by(rfid_tag=id_tag, is_active=True).first()
            if card:
                tariff = self._resolve_tariff(db, card.customer_id)
                session = models.ChargingSession(
                    charge_point_db_id=self._db_cp_id,
                    connector_id=connector_id,
                    card_id=card.id,
                    customer_id=card.customer_id,
                    tariff_id=tariff.id if tariff else None,
                    meter_start=float(meter_start),
                    start_time=start_time,
                    cost_connection=tariff.connection_fee if tariff else 0.0,
                    status="active",
                )
                db.add(session)
                db.commit()
                db.refresh(session)
                session.transaction_id = session.id
                db.commit()
                logger.info("StartTransaction (local): session_id=%d tag=%s", session.id, id_tag)
                return call_result.StartTransaction(
                    transaction_id=session.id,
                    id_tag_info={"status": AuthorizationStatus.accepted},
                )

            # 2. Try OCPI token (Fremdkarte) – use default tariff for billing
            ocpi_tok = db.query(models.OcpiToken).filter_by(uid=id_tag, valid=True).first()
            if ocpi_tok:
                tariff = db.query(models.Tariff).filter_by(is_default=True).first()
                session = models.ChargingSession(
                    charge_point_db_id=self._db_cp_id,
                    connector_id=connector_id,
                    tariff_id=tariff.id if tariff else None,
                    ocpi_token_id=ocpi_tok.id,
                    meter_start=float(meter_start),
                    start_time=start_time,
                    cost_connection=tariff.connection_fee if tariff else 0.0,
                    status="active",
                )
                db.add(session)
                db.commit()
                db.refresh(session)
                session.transaction_id = session.id
                db.commit()
                logger.info("StartTransaction (OCPI roaming): session_id=%d tag=%s party=%s/%s",
                            session.id, id_tag, ocpi_tok.party.country_code, ocpi_tok.party.party_id)
                return call_result.StartTransaction(
                    transaction_id=session.id,
                    id_tag_info={"status": AuthorizationStatus.accepted},
                )

            # Unknown card
            logger.warning("StartTransaction rejected: unknown tag %s", id_tag)
            session = models.ChargingSession(
                charge_point_db_id=self._db_cp_id,
                connector_id=connector_id,
                meter_start=float(meter_start),
                start_time=start_time,
                status="failed",
                stop_reason="UnknownCard",
            )
            db.add(session)
            db.commit()
            db.refresh(session)
            session.transaction_id = session.id
            db.commit()
            return call_result.StartTransaction(
                transaction_id=session.id,
                id_tag_info={"status": AuthorizationStatus.invalid},
            )
        finally:
            db.close()

    # ── MeterValues ───────────────────────────────────────────────────────────

    @on(Action.MeterValues)
    async def on_meter_values(
        self,
        connector_id: int,
        meter_value: list,
        transaction_id: int = 0,
        **kwargs,
    ):
        db = self._get_db()
        try:
            session = db.query(models.ChargingSession).filter_by(
                transaction_id=transaction_id, status="active"
            ).first()
            if not session:
                return call_result.MeterValues()

            for mv in meter_value:
                for sv in mv.get("sampled_value", []):
                    measurand = sv.get("measurand", "Energy.Active.Import.Register")
                    unit = sv.get("unit", "Wh")
                    if measurand == "Energy.Active.Import.Register":
                        try:
                            raw = float(sv["value"])
                            wh = raw * 1000 if unit == "kWh" else raw
                            session.meter_stop = wh
                        except (KeyError, ValueError):
                            pass
            db.commit()
        finally:
            db.close()
        return call_result.MeterValues()

    # ── StopTransaction ───────────────────────────────────────────────────────

    @on(Action.StopTransaction)
    async def on_stop_transaction(
        self,
        meter_stop: int,
        timestamp: str,
        transaction_id: int,
        reason: str = "Local",
        id_tag: str = "",
        **kwargs,
    ):
        db = self._get_db()
        cdr_id_to_push: int | None = None
        try:
            session = db.query(models.ChargingSession).filter_by(transaction_id=transaction_id).first()
            if not session:
                logger.warning("StopTransaction for unknown transaction_id=%d", transaction_id)
                return call_result.StopTransaction()

            end_time = _parse_dt(timestamp) or _utcnow()
            session.end_time = end_time
            session.meter_stop = float(meter_stop)
            session.stop_reason = reason

            if session.start_time and session.status == "active":
                tariff = session.tariff
                result = calculate_cost(
                    meter_start_wh=session.meter_start,
                    meter_stop_wh=session.meter_stop,
                    session_start=session.start_time,
                    session_end=end_time,
                    charging_stopped_at=session.charging_stopped_at,
                    price_per_kwh=tariff.price_per_kwh if tariff else 0.0,
                    price_per_minute=tariff.price_per_minute if tariff else 0.0,
                    connection_fee=tariff.connection_fee if tariff else 0.0,
                    blocking_fee_per_minute=tariff.blocking_fee_per_minute if tariff else 0.0,
                    blocking_grace_period_minutes=tariff.blocking_grace_period_minutes if tariff else 0,
                )
                session.energy_kwh = result.energy_kwh
                session.duration_minutes = result.duration_minutes
                session.charging_minutes = result.charging_minutes
                session.blocking_minutes = result.blocking_minutes
                session.cost_energy = result.cost_energy
                session.cost_time = result.cost_time
                session.cost_connection = result.cost_connection
                session.cost_blocking = result.cost_blocking
                session.total_cost = result.total_cost

                if session.card:
                    session.card.balance = max(0.0, session.card.balance - result.total_cost)

                session.status = "completed"

                logger.info(
                    "StopTransaction: session_id=%d energy=%.3f kWh cost=%.2f € "
                    "(energy=%.2f + time=%.2f + conn=%.2f + blocking=%.2f)",
                    session.id, result.energy_kwh, result.total_cost,
                    result.cost_energy, result.cost_time, result.cost_connection, result.cost_blocking,
                )

                # ── OCPI CDR for roaming sessions ──────────────────────────
                if session.ocpi_token_id:
                    ocpi_tok = session.ocpi_token
                    cp = session.charge_point
                    cdr = models.OcpiCdr(
                        cdr_id=str(uuid.uuid4()),
                        session_db_id=session.id,
                        party_id_ref=ocpi_tok.party_id_ref,
                        start_date_time=session.start_time,
                        end_date_time=end_time,
                        token_uid=ocpi_tok.uid,
                        contract_id=ocpi_tok.contract_id,
                        charge_point_ocpp_id=cp.charge_point_id if cp else None,
                        total_energy=result.energy_kwh,
                        total_time_hours=round(result.duration_minutes / 60, 4),
                        total_cost=result.total_cost,
                        currency="EUR",
                        status="PENDING",
                    )
                    db.add(cdr)
                    db.commit()
                    db.refresh(cdr)
                    cdr_id_to_push = cdr.id
                    logger.info("Created OCPI CDR %s for roaming session %d", cdr.cdr_id, session.id)

            db.commit()
        finally:
            db.close()

        # Push CDR asynchronously so we don't block the OCPP response
        if cdr_id_to_push:
            from ocpi.cdr_push import push_cdr
            asyncio.create_task(push_cdr(cdr_id_to_push))

        return call_result.StopTransaction()


# ─── WebSocket entry point ────────────────────────────────────────────────────

async def on_connect(websocket: WebSocket, charge_point_id: str):
    await websocket.accept(subprotocol="ocpp1.6")
    logger.info("Charge point connected: %s", charge_point_id)
    cp = ChargePoint16(charge_point_id, websocket)
    try:
        await cp.start()
    except Exception as exc:
        logger.info("Charge point %s disconnected: %s", charge_point_id, exc)
