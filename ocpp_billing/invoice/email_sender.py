"""Send invoice PDF via SMTP. Settings are loaded from SystemSettings table."""

import logging
import smtplib
from datetime import datetime, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from database import SessionLocal
import models

logger = logging.getLogger("invoice.email")


def _get_setting(db, key: str, default: str = "") -> str:
    s = db.query(models.SystemSettings).filter_by(key=key).first()
    return s.value if s else default


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def send_invoice_email(invoice_id: int, db=None) -> bool:
    """Send invoice PDF by email. Returns True on success."""
    close_db = db is None
    if db is None:
        db = SessionLocal()

    try:
        invoice = db.query(models.Invoice).filter_by(id=invoice_id).first()
        if not invoice:
            logger.warning("Invoice %d not found", invoice_id)
            return False

        customer = invoice.customer
        if not customer or not customer.email:
            logger.warning("No email address for invoice %d", invoice_id)
            return False

        if not invoice.pdf_path or not Path(invoice.pdf_path).exists():
            logger.warning("PDF missing for invoice %d, regenerating", invoice_id)
            try:
                from invoice.generator import generate_invoice_pdf
                generate_invoice_pdf(invoice_id, db)
                db.refresh(invoice)
            except Exception as e:
                logger.error("PDF regeneration failed: %s", e)
                return False

        smtp_host = _get_setting(db, "smtp_host")
        if not smtp_host:
            logger.warning("SMTP not configured – skipping email for invoice %d", invoice_id)
            return False

        smtp_port = int(_get_setting(db, "smtp_port", "587"))
        smtp_user = _get_setting(db, "smtp_user")
        smtp_pass = _get_setting(db, "smtp_password")
        smtp_from = _get_setting(db, "smtp_from", smtp_user)
        co_name   = _get_setting(db, "company_name", "Charging Station")
        due_str   = invoice.due_date.strftime("%d.%m.%Y") if invoice.due_date else "-"

        msg = MIMEMultipart()
        msg["From"]    = f"{co_name} <{smtp_from}>"
        msg["To"]      = customer.email
        msg["Subject"] = f"Ihre Rechnung {invoice.invoice_number}"

        body = (
            f"Sehr geehrte/r {customer.name},\n\n"
            f"anbei erhalten Sie Ihre Rechnung {invoice.invoice_number} "
            f"über {invoice.amount_gross:.2f} € (inkl. MwSt.).\n\n"
            f"Bitte überweisen Sie den Betrag bis zum {due_str} "
            f"unter Angabe der Rechnungsnummer.\n\n"
            f"Vielen Dank für das Laden bei uns!\n\n"
            f"Mit freundlichen Grüßen\n{co_name}"
        )
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with open(invoice.pdf_path, "rb") as f:
            part = MIMEBase("application", "pdf")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{invoice.invoice_number}.pdf"',
        )
        msg.attach(part)

        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            if smtp_user and smtp_pass:
                smtp.login(smtp_user, smtp_pass)
            smtp.sendmail(smtp_from, [customer.email], msg.as_string())

        invoice.email_sent_at = _utcnow()
        invoice.email_to = customer.email
        if invoice.status == "ISSUED":
            invoice.status = "SENT"
        db.commit()

        logger.info("Sent invoice %s to %s", invoice.invoice_number, customer.email)
        return True

    except Exception as e:
        logger.error("Email send failed for invoice %d: %s", invoice_id, e)
        return False

    finally:
        if close_db:
            db.close()
