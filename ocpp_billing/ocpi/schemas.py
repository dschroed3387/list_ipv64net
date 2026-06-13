"""
OCPI 2.2.1 Pydantic schemas.
Only fields relevant for CPO operation are included.
"""

from pydantic import BaseModel
from typing import Any, Optional


# ─── Generic envelope ────────────────────────────────────────────────────────

class OcpiResponse(BaseModel):
    data: Any
    status_code: int = 1000
    status_message: str = "Success"
    timestamp: str


# ─── Credentials ─────────────────────────────────────────────────────────────

class BusinessDetails(BaseModel):
    name: str
    website: Optional[str] = None
    logo: Optional[dict] = None


class CredentialsRole(BaseModel):
    role: str                        # EMSP | CPO | HUB | NAP | NSP | OTHER | SCSP
    business_details: BusinessDetails
    country_code: str                # ISO 3166-1 alpha-2
    party_id: str                    # 3-letter party identifier


class CredentialsIn(BaseModel):
    token: str                       # token they want us to use when calling them
    url: str                         # their versions URL
    roles: list[CredentialsRole]


class CredentialsOut(BaseModel):
    token: str
    url: str
    roles: list[CredentialsRole]


# ─── Token (Fremdkarte) ───────────────────────────────────────────────────────

class OcpiTokenIn(BaseModel):
    uid: str
    type: str = "RFID"
    contract_id: str
    visual_number: Optional[str] = None
    issuer: str
    group_id: Optional[str] = None
    valid: bool = True
    whitelist: str = "ALLOWED"
    language: Optional[str] = None
    last_updated: str


class OcpiTokenOut(OcpiTokenIn):
    country_code: str
    party_id: str


# ─── EVSE / Location ──────────────────────────────────────────────────────────

class OcpiConnector(BaseModel):
    id: str
    standard: str = "IEC_62196_T2"
    format: str = "SOCKET"
    power_type: str = "AC_3_PHASE"
    max_voltage: int = 400
    max_amperage: int = 32
    last_updated: str


class OcpiEvse(BaseModel):
    uid: str
    evse_id: Optional[str] = None
    status: str
    connectors: list[OcpiConnector]
    last_updated: str


class OcpiGeoLocation(BaseModel):
    latitude: str
    longitude: str


class OcpiLocation(BaseModel):
    country_code: str
    party_id: str
    id: str
    publish: bool = True
    name: str
    address: str
    city: str
    postal_code: Optional[str] = None
    country: str
    coordinates: Optional[OcpiGeoLocation] = None
    evses: list[OcpiEvse] = []
    last_updated: str


# ─── CDR ─────────────────────────────────────────────────────────────────────

class OcpiCdrToken(BaseModel):
    country_code: str
    party_id: str
    uid: str
    type: str = "RFID"
    contract_id: str


class OcpiPriceDimension(BaseModel):
    type: str           # ENERGY | TIME | FLAT | PARKING_TIME
    volume: float
    price: float


class OcpiChargingPeriod(BaseModel):
    start_date_time: str
    dimensions: list[OcpiPriceDimension]
    tariff_id: Optional[str] = None


class OcpiPrice(BaseModel):
    excl_vat: float
    incl_vat: Optional[float] = None


class OcpiCdrLocation(BaseModel):
    id: str
    name: str
    address: str
    city: str
    country: str
    coordinates: Optional[OcpiGeoLocation] = None
    evse_uid: str
    evse_id: Optional[str] = None
    connector_id: str
    connector_standard: str = "IEC_62196_T2"
    connector_format: str = "SOCKET"
    connector_power_type: str = "AC_3_PHASE"


class OcpiCdrOut(BaseModel):
    country_code: str
    party_id: str
    id: str
    start_date_time: str
    end_date_time: str
    session_id: Optional[str] = None
    cdr_token: OcpiCdrToken
    auth_method: str = "AUTH_REQUEST"
    cdr_location: OcpiCdrLocation
    currency: str = "EUR"
    charging_periods: list[OcpiChargingPeriod]
    total_cost: OcpiPrice
    total_energy: float
    total_time: float
    total_parking_time: Optional[float] = None
    last_updated: str


# ─── Session (active) ─────────────────────────────────────────────────────────

class OcpiSessionOut(BaseModel):
    country_code: str
    party_id: str
    id: str
    start_date_time: str
    end_date_time: Optional[str] = None
    kwh: float
    cdr_token: OcpiCdrToken
    auth_method: str = "AUTH_REQUEST"
    location_id: str
    evse_uid: str
    connector_id: str
    currency: str = "EUR"
    status: str          # ACTIVE | COMPLETED | INVALID | PENDING | RESERVATION
    last_updated: str


# ─── Admin schemas ────────────────────────────────────────────────────────────

class PartyCreate(BaseModel):
    country_code: str
    party_id: str
    role: str = "EMSP"
    name: str
    website: Optional[str] = None
    our_token: str           # token we assign; eMSP must use this in Authorization header
    their_token: Optional[str] = None
    their_versions_url: Optional[str] = None
    their_cdrs_url: Optional[str] = None


class PartyUpdate(BaseModel):
    name: Optional[str] = None
    website: Optional[str] = None
    their_token: Optional[str] = None
    their_versions_url: Optional[str] = None
    their_cdrs_url: Optional[str] = None
    status: Optional[str] = None


class PartyOut(BaseModel):
    id: int
    country_code: str
    party_id: str
    role: str
    name: Optional[str]
    website: Optional[str]
    our_token: str
    their_token: Optional[str]
    their_versions_url: Optional[str]
    their_cdrs_url: Optional[str]
    status: str
    created_at: Any
    last_updated: Any
    token_count: int = 0
    cdr_count: int = 0

    model_config = {"from_attributes": True}


class OcpiTokenAdminOut(BaseModel):
    id: int
    party_id_ref: int
    uid: str
    type: str
    contract_id: Optional[str]
    visual_number: Optional[str]
    issuer: Optional[str]
    group_id: Optional[str]
    valid: bool
    whitelist: str
    last_updated: Any

    model_config = {"from_attributes": True}


class OcpiCdrAdminOut(BaseModel):
    id: int
    cdr_id: str
    session_db_id: Optional[int]
    party_id_ref: int
    token_uid: Optional[str]
    total_energy: float
    total_cost: float
    currency: str
    status: str
    push_attempts: int
    sent_at: Any
    error_message: Optional[str]
    created_at: Any

    model_config = {"from_attributes": True}
