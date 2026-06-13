from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


# ─── Customer ────────────────────────────────────────────────────────────────

class CustomerCreate(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    company: Optional[str] = None
    vat_id: Optional[str] = None
    address: Optional[str] = None


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    vat_id: Optional[str] = None
    address: Optional[str] = None
    is_active: Optional[bool] = None


class CustomerOut(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str]
    company: Optional[str]
    vat_id: Optional[str]
    address: Optional[str]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── TariffPeriod ─────────────────────────────────────────────────────────────

class TariffPeriodCreate(BaseModel):
    name: str
    weekdays: str = Field("", description="Comma-separated weekday numbers 0=Mon…6=Sun, empty=every day")
    hour_from: int = Field(0, ge=0, le=23)
    hour_to: int = Field(23, ge=0, le=23)
    price_per_kwh: float = Field(..., ge=0, description="€/kWh for this period")
    price_per_minute: float = Field(0.0, ge=0, description="€/min during this period")
    priority: int = Field(0, ge=0, description="Higher priority wins when multiple periods match")


class TariffPeriodUpdate(BaseModel):
    name: Optional[str] = None
    weekdays: Optional[str] = None
    hour_from: Optional[int] = Field(None, ge=0, le=23)
    hour_to: Optional[int] = Field(None, ge=0, le=23)
    price_per_kwh: Optional[float] = Field(None, ge=0)
    price_per_minute: Optional[float] = Field(None, ge=0)
    priority: Optional[int] = Field(None, ge=0)


class TariffPeriodOut(BaseModel):
    id: int
    tariff_id: int
    name: str
    weekdays: str
    hour_from: int
    hour_to: int
    price_per_kwh: float
    price_per_minute: float
    priority: int

    model_config = {"from_attributes": True}


# ─── Tariff ──────────────────────────────────────────────────────────────────

class TariffCreate(BaseModel):
    name: str
    description: Optional[str] = None
    customer_id: Optional[int] = None
    price_per_kwh: float = Field(0.0, ge=0, description="€/kWh")
    price_per_minute: float = Field(0.0, ge=0, description="€/min during charging")
    connection_fee: float = Field(0.0, ge=0, description="Flat fee per session (€)")
    blocking_fee_per_minute: float = Field(0.0, ge=0, description="€/min Blockiergebühr")
    blocking_grace_period_minutes: int = Field(10, ge=0)
    is_default: bool = False


class TariffUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price_per_kwh: Optional[float] = Field(None, ge=0)
    price_per_minute: Optional[float] = Field(None, ge=0)
    connection_fee: Optional[float] = Field(None, ge=0)
    blocking_fee_per_minute: Optional[float] = Field(None, ge=0)
    blocking_grace_period_minutes: Optional[int] = Field(None, ge=0)
    is_default: Optional[bool] = None


class TariffOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    customer_id: Optional[int]
    price_per_kwh: float
    price_per_minute: float
    connection_fee: float
    blocking_fee_per_minute: float
    blocking_grace_period_minutes: int
    is_default: bool
    created_at: datetime
    periods: list[TariffPeriodOut] = []

    model_config = {"from_attributes": True}


# ─── Card ────────────────────────────────────────────────────────────────────

class CardCreate(BaseModel):
    rfid_tag: str
    customer_id: int
    label: Optional[str] = None
    balance: float = Field(0.0, ge=0, description="Initial prepaid balance in €")


class CardUpdate(BaseModel):
    label: Optional[str] = None
    is_active: Optional[bool] = None


class CardBalanceAdd(BaseModel):
    amount: float = Field(..., gt=0, description="Amount in € to add to card balance")


class CardOut(BaseModel):
    id: int
    rfid_tag: str
    customer_id: int
    label: Optional[str]
    is_active: bool
    balance: float
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── ChargePoint ─────────────────────────────────────────────────────────────

class ChargePointOut(BaseModel):
    id: int
    charge_point_id: str
    vendor: Optional[str]
    model: Optional[str]
    serial_number: Optional[str]
    firmware_version: Optional[str]
    status: str
    last_heartbeat: Optional[datetime]
    registered_at: datetime

    model_config = {"from_attributes": True}


# ─── ChargingSession ─────────────────────────────────────────────────────────

class SessionOut(BaseModel):
    id: int
    transaction_id: Optional[int]
    charge_point_db_id: Optional[int]
    connector_id: int
    card_id: Optional[int]
    customer_id: Optional[int]
    tariff_id: Optional[int]
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    charging_stopped_at: Optional[datetime]
    meter_start: float
    meter_stop: float
    energy_kwh: float
    duration_minutes: float
    charging_minutes: float
    blocking_minutes: float
    cost_energy: float
    cost_time: float
    cost_connection: float
    cost_blocking: float
    total_cost: float
    co2_saved_kg: float
    status: str
    stop_reason: Optional[str]

    model_config = {"from_attributes": True}


# ─── Invoice (session detail view – existing endpoint) ────────────────────────

class InvoiceOut(BaseModel):
    session_id: int
    transaction_id: Optional[int]
    charge_point_id: Optional[str]
    connector_id: int
    customer_name: Optional[str]
    customer_email: Optional[str]
    card_rfid: Optional[str]
    tariff_name: Optional[str]
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    energy_kwh: float
    duration_minutes: float
    charging_minutes: float
    blocking_minutes: float
    blocking_grace_period_minutes: int
    price_per_kwh: float
    price_per_minute: float
    connection_fee: float
    blocking_fee_per_minute: float
    cost_energy: float
    cost_time: float
    cost_connection: float
    cost_blocking: float
    total_cost: float
    co2_saved_kg: float
    status: str
    stop_reason: Optional[str]

    model_config = {"from_attributes": True}


# ─── Invoice (DB record) ──────────────────────────────────────────────────────

class InvoiceRecordOut(BaseModel):
    id: int
    invoice_number: str
    session_db_id: Optional[int]
    customer_id: Optional[int]
    invoice_date: Optional[datetime]
    due_date: Optional[datetime]
    amount_net: float
    vat_rate: float
    vat_amount: float
    amount_gross: float
    currency: str
    co2_saved_kg: float
    status: str
    pdf_path: Optional[str]
    email_sent_at: Optional[datetime]
    email_to: Optional[str]
    paid_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── System Settings ──────────────────────────────────────────────────────────

class SystemSettingOut(BaseModel):
    key: str
    value: str
    description: Optional[str]

    model_config = {"from_attributes": True}


class SystemSettingsUpdate(BaseModel):
    settings: dict[str, str]
