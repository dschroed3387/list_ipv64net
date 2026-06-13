from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SystemSettings(Base):
    """Key-value store for system-wide configuration."""
    __tablename__ = "system_settings"
    key = Column(String(100), primary_key=True)
    value = Column(Text, default="")
    description = Column(String(500))


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    phone = Column(String(50))
    company = Column(String(255))       # Firmenname (for B2B invoices)
    vat_id = Column(String(50))         # Umsatzsteuer-ID (B2B)
    address = Column(Text)
    created_at = Column(DateTime, default=utcnow)
    is_active = Column(Boolean, default=True)

    cards = relationship("Card", back_populates="customer", cascade="all, delete-orphan")
    tariff = relationship("Tariff", back_populates="customer", uselist=False)
    sessions = relationship("ChargingSession", back_populates="customer")
    invoices = relationship("Invoice", back_populates="customer")


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
    periods = relationship("TariffPeriod", back_populates="tariff",
                           cascade="all, delete-orphan", order_by="TariffPeriod.priority.desc()")


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

    # Applied tariff period (if dynamic pricing was used)
    tariff_period_id = Column(Integer, ForeignKey("tariff_periods.id"), nullable=True)

    # CO₂ savings vs. equivalent ICE vehicle (kg)
    co2_saved_kg = Column(Float, default=0.0)

    status = Column(String(50), default="active")  # active | completed | failed
    stop_reason = Column(String(100))

    # OCPI roaming: set when session started with a Fremdkarte
    ocpi_token_id = Column(Integer, ForeignKey("ocpi_tokens.id"), nullable=True)

    charge_point = relationship("ChargePoint", back_populates="sessions")
    card = relationship("Card", back_populates="sessions")
    customer = relationship("Customer", back_populates="sessions")
    tariff = relationship("Tariff", back_populates="sessions")
    tariff_period = relationship("TariffPeriod", back_populates="sessions")
    ocpi_token = relationship("OcpiToken", back_populates="sessions")
    ocpi_cdr = relationship("OcpiCdr", back_populates="session", uselist=False)
    invoice = relationship("Invoice", back_populates="session", uselist=False)


# ─── OCPI Models ─────────────────────────────────────────────────────────────

class OcpiParty(Base):
    """Registered eMSP / roaming partner for OCPI interoperability."""
    __tablename__ = "ocpi_parties"

    id = Column(Integer, primary_key=True, index=True)
    country_code = Column(String(2), nullable=False)   # ISO 3166, e.g. "DE"
    party_id = Column(String(3), nullable=False)        # 3-letter, e.g. "EMP"
    role = Column(String(10), default="EMSP")           # EMSP | CPO | HUB
    name = Column(String(255))
    website = Column(String(500))

    # Token the eMSP uses when calling our OCPI endpoints
    our_token = Column(String(255), unique=True, nullable=False)
    # Token we use when pushing CDRs to the eMSP
    their_token = Column(String(255))
    # eMSP's OCPI versions URL (for CDR push discovery)
    their_versions_url = Column(String(500))
    # Resolved CDR push URL (cached after handshake)
    their_cdrs_url = Column(String(500))

    status = Column(String(20), default="PENDING")  # PENDING | CONNECTED | SUSPENDED
    created_at = Column(DateTime, default=utcnow)
    last_updated = Column(DateTime, default=utcnow)

    tokens = relationship("OcpiToken", back_populates="party", cascade="all, delete-orphan")
    cdrs = relationship("OcpiCdr", back_populates="party")


class OcpiToken(Base):
    """RFID card / token issued by an external eMSP (Fremdkarte)."""
    __tablename__ = "ocpi_tokens"

    id = Column(Integer, primary_key=True, index=True)
    party_id_ref = Column(Integer, ForeignKey("ocpi_parties.id"), nullable=False)

    uid = Column(String(255), unique=True, nullable=False, index=True)  # RFID UID
    type = Column(String(20), default="RFID")          # RFID | APP_USER | AD_HOC_USER | OTHER
    contract_id = Column(String(255))                  # EMA-ID / auth_id
    visual_number = Column(String(255))                # Human-readable card number
    issuer = Column(String(255))                       # eMSP name
    group_id = Column(String(255))                     # Fleet/group identifier
    valid = Column(Boolean, default=True)
    whitelist = Column(String(20), default="ALLOWED")  # ALWAYS | ALLOWED | ALLOWED_OFFLINE | NEVER
    last_updated = Column(DateTime, default=utcnow)

    party = relationship("OcpiParty", back_populates="tokens")
    sessions = relationship("ChargingSession", back_populates="ocpi_token")


class OcpiCdr(Base):
    """Charge Detail Record – generated after a roaming session, pushed to eMSP."""
    __tablename__ = "ocpi_cdrs"

    id = Column(Integer, primary_key=True, index=True)
    cdr_id = Column(String(255), unique=True, nullable=False)  # our globally unique CDR ID
    session_db_id = Column(Integer, ForeignKey("charging_sessions.id"), unique=True)
    party_id_ref = Column(Integer, ForeignKey("ocpi_parties.id"), nullable=False)

    start_date_time = Column(DateTime)
    end_date_time = Column(DateTime)
    token_uid = Column(String(255))
    contract_id = Column(String(255))
    charge_point_ocpp_id = Column(String(255))         # human-readable station ID

    total_energy = Column(Float, default=0.0)          # kWh
    total_time_hours = Column(Float, default=0.0)      # decimal hours
    total_cost = Column(Float, default=0.0)            # €
    currency = Column(String(3), default="EUR")

    # Push lifecycle
    status = Column(String(20), default="PENDING")     # PENDING | SENT | FAILED | ACCEPTED
    push_attempts = Column(Integer, default=0)
    sent_at = Column(DateTime)
    error_message = Column(Text)
    created_at = Column(DateTime, default=utcnow)

    session = relationship("ChargingSession", back_populates="ocpi_cdr")
    party = relationship("OcpiParty", back_populates="cdrs")


# ─── Invoice / Billing Models ─────────────────────────────────────────────────

class Invoice(Base):
    """PDF invoice generated after each completed charging session."""
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String(50), unique=True, nullable=False, index=True)
    session_db_id = Column(Integer, ForeignKey("charging_sessions.id"), unique=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)

    invoice_date = Column(DateTime, default=utcnow)
    due_date = Column(DateTime)

    # VAT breakdown (all amounts in EUR)
    amount_net = Column(Float, default=0.0)
    vat_rate = Column(Float, default=0.19)     # e.g. 0.19 = 19%
    vat_amount = Column(Float, default=0.0)
    amount_gross = Column(Float, default=0.0)
    currency = Column(String(3), default="EUR")

    # Environmental info
    co2_saved_kg = Column(Float, default=0.0)

    # Lifecycle
    status = Column(String(20), default="ISSUED")  # ISSUED | SENT | PAID | CANCELLED
    pdf_path = Column(String(500))
    email_sent_at = Column(DateTime)
    email_to = Column(String(255))
    paid_at = Column(DateTime)
    created_at = Column(DateTime, default=utcnow)

    session = relationship("ChargingSession", back_populates="invoice")
    customer = relationship("Customer", back_populates="invoices")


class TariffPeriod(Base):
    """Dynamic pricing period – overrides base tariff rates at specific times."""
    __tablename__ = "tariff_periods"

    id = Column(Integer, primary_key=True, index=True)
    tariff_id = Column(Integer, ForeignKey("tariffs.id"), nullable=False)
    name = Column(String(100), nullable=False)   # e.g. "Hauptverbrauchszeit", "Wochenende"
    # Comma-separated weekday numbers (0=Mon … 6=Sun); empty = every day
    weekdays = Column(String(20), default="")
    hour_from = Column(Integer, default=0)       # 0–23 inclusive
    hour_to = Column(Integer, default=23)        # 0–23 inclusive
    price_per_kwh = Column(Float, nullable=False)
    price_per_minute = Column(Float, default=0.0)
    # Higher priority period wins when multiple periods match
    priority = Column(Integer, default=0)

    tariff = relationship("Tariff", back_populates="periods")
    sessions = relationship("ChargingSession", back_populates="tariff_period")
