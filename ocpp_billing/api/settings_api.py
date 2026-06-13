from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
import models
import schemas

router = APIRouter()

# Default settings with (value, description)
DEFAULTS: dict[str, tuple[str, str]] = {
    "company_name":        ("Charging Station GmbH",   "Firmenname für Rechnungen"),
    "company_address":     ("Musterstraße 1\n12345 Musterstadt", "Postanschrift (Zeilenumbruch mit \\n)"),
    "company_tax_number":  ("",                        "Steuernummer (z.B. 12/345/67890)"),
    "company_vat_id":      ("",                        "Umsatzsteuer-ID (z.B. DE123456789)"),
    "company_iban":        ("",                        "IBAN für Banküberweisung"),
    "company_bic":         ("",                        "BIC / SWIFT-Code"),
    "company_bank":        ("",                        "Bankname"),
    "company_phone":       ("",                        "Telefonnummer"),
    "company_email":       ("",                        "Kontakt-E-Mail"),
    "company_website":     ("",                        "Website-URL"),
    "vat_rate":            ("0.19",                    "MwSt-Satz (0.19 = 19%)"),
    "invoice_due_days":    ("14",                      "Zahlungsziel in Tagen ab Rechnungsdatum"),
    "auto_send_email":     ("false",                   "Rechnung automatisch per E-Mail senden (true/false)"),
    "co2_factor_kg_per_kwh": ("0.67",                 "CO₂-Einsparfaktor in kg pro kWh ggü. Verbrenner"),
    "smtp_host":           ("",                        "SMTP-Servername"),
    "smtp_port":           ("587",                     "SMTP-Port (Standard: 587 für STARTTLS)"),
    "smtp_user":           ("",                        "SMTP-Benutzername"),
    "smtp_password":       ("",                        "SMTP-Passwort"),
    "smtp_from":           ("",                        "Absender-E-Mail-Adresse"),
}


def seed_default_settings(db: Session) -> None:
    """Insert default settings that don't exist yet."""
    for key, (value, desc) in DEFAULTS.items():
        if not db.query(models.SystemSettings).filter_by(key=key).first():
            db.add(models.SystemSettings(key=key, value=value, description=desc))
    db.commit()


@router.get("/", response_model=list[schemas.SystemSettingOut])
def get_all_settings(db: Session = Depends(get_db)):
    return db.query(models.SystemSettings).order_by(models.SystemSettings.key).all()


@router.get("/{key}", response_model=schemas.SystemSettingOut)
def get_setting(key: str, db: Session = Depends(get_db)):
    s = db.query(models.SystemSettings).filter_by(key=key).first()
    if not s:
        raise HTTPException(404, f"Setting '{key}' not found")
    return s


@router.put("/")
def update_settings(body: schemas.SystemSettingsUpdate, db: Session = Depends(get_db)):
    updated = 0
    for key, value in body.settings.items():
        s = db.query(models.SystemSettings).filter_by(key=key).first()
        if s:
            s.value = value
        else:
            desc = DEFAULTS.get(key, ("", ""))[1]
            db.add(models.SystemSettings(key=key, value=value, description=desc))
        updated += 1
    db.commit()
    return {"detail": f"{updated} Einstellung(en) gespeichert"}
