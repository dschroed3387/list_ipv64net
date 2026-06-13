from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    phone = Column(String(50))
    address = Column(Text)
    created_at = Column(DateTime, default=utcnow)
    is_active = Column(Boolean, default=True)

    cards = relationship("Card", back_populates="customer", cascade="all, delete-orphan")
    tariff = relationship("Tariff", back_populates="customer", uselist=False)
    sessions = relationship("ChargingSession", back_populates="customer")


class Tariff(Base):
    """
    Tariff model. A customer-specific tariff overrides the default.
    Blocking fee: charged per minute after charging stops but car stays plugged in,
    after the grace period expires.
    """
    __tablename__ = "tariffs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, unique=True)

    # Core energy / time pricing
    price_per_kwh = Column(Float, default=0.0)           # €/kWh
    price_per_minute = Column(Float, default=0.0)        # €/min during charging
    connection_fee = Column(Float, default=0.0)          # flat fee per session start

    # Blocking fee (Blockiergebühr)
    blocking_fee_per_minute = Column(Float, default=0.0) # €/min after grace period
    blocking_grace_period_minutes = Column(Integer, default=10)  # free minutes after charge end

    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

    customer = relationship("Customer", back_populates="tariff")
    sessions = relationship("ChargingSession", back_populates="tariff")


class Card(Base):
    """RFID card linked to a customer."""
    __tablename__ = "cards"

    id = Column(Integer, primary_key=True, index=True)
    rfid_tag = Column(String(255), unique=True, nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    label = Column(String(255))
    is_active = Column(Boolean, default=True)
    balance = Column(Float, default=0.0)    # prepaid balance in €
    created_at = Column(DateTime, default=utcnow)

    customer = relationship("Customer", back_populates="cards")
    sessions = relationship("ChargingSession", back_populates="card")


class ChargePoint(Base):
    """Registered OCPP charge point (Ladesäule)."""
    __tablename__ = "charge_points"

    id = Column(Integer, primary_key=True, index=True)
    charge_point_id = Column(String(255), unique=True, nullable=False, index=True)
    vendor = Column(String(255))
    model = Column(String(255))
    serial_number = Column(String(255))
    firmware_version = Column(String(100))
    status = Column(String(50), default="Unknown")
    last_heartbeat = Column(DateTime)
    registered_at = Column(DateTime, default=utcnow)

    sessions = relationship("ChargingSession", back_populates="charge_point")


class ChargingSession(Base):
    """One complete charging transaction."""
    __tablename__ = "charging_sessions"

    id = Column(Integer, primary_key=True, index=True)
    charge_point_db_id = Column(Integer, ForeignKey("charge_points.id"))
    connector_id = Column(Integer, default=1)
    card_id = Column(Integer, ForeignKey("cards.id"))
    customer_id = Column(Integer, ForeignKey("customers.id"))
    tariff_id = Column(Integer, ForeignKey("tariffs.id"))

    # OCPP transaction ID returned in StartTransaction response
    transaction_id = Column(Integer, unique=True, index=True)

    start_time = Column(DateTime)
    end_time = Column(DateTime)
    # Timestamp when charging power dropped to 0 (EV full / suspended)
    charging_stopped_at = Column(DateTime)

    # Meter values in Wh
    meter_start = Column(Float, default=0.0)
    meter_stop = Column(Float, default=0.0)

    # Derived on session close
    energy_kwh = Column(Float, default=0.0)
    duration_minutes = Column(Float, default=0.0)
    charging_minutes = Column(Float, default=0.0)  # time power was flowing
    blocking_minutes = Column(Float, default=0.0)  # chargeable blocking time

    # Cost breakdown in €
    cost_energy = Column(Float, default=0.0)
    cost_time = Column(Float, default=0.0)
    cost_connection = Column(Float, default=0.0)
    cost_blocking = Column(Float, default=0.0)
    total_cost = Column(Float, default=0.0)

    status = Column(String(50), default="active")  # active | completed | failed
    stop_reason = Column(String(100))

    charge_point = relationship("ChargePoint", back_populates="sessions")
    card = relationship("Card", back_populates="sessions")
    customer = relationship("Customer", back_populates="sessions")
    tariff = relationship("Tariff", back_populates="sessions")
