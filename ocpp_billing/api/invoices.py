from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
import models
import schemas

router = APIRouter()


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("/", response_model=list[schemas.InvoiceRecordOut])
def list_invoices(
    status: str | None = None,
    customer_id: int | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.Invoice)
    if status:
        q = q.filter_by(status=status)
    if customer_id:
        q = q.filter_by(customer_id=customer_id)
    return q.order_by(models.Invoice.id.desc()).all()


@router.get("/{invoice_id}", response_model=schemas.InvoiceRecordOut)
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    inv = db.query(models.Invoice).filter_by(id=invoice_id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return inv


@router.get("/{invoice_id}/pdf")
def download_pdf(invoice_id: int, db: Session = Depends(get_db)):
    """Download or regenerate the PDF for an invoice."""
    inv = db.query(models.Invoice).filter_by(id=invoice_id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")

    if not inv.pdf_path or not Path(inv.pdf_path).exists():
        try:
            from invoice.generator import generate_invoice_pdf
            generate_invoice_pdf(invoice_id, db)
            db.refresh(inv)
        except Exception as e:
            raise HTTPException(500, f"PDF generation failed: {e}")

    if not inv.pdf_path or not Path(inv.pdf_path).exists():
        raise HTTPException(404, "PDF could not be generated")

    return FileResponse(
        inv.pdf_path,
        media_type="application/pdf",
        filename=f"{inv.invoice_number}.pdf",
    )


@router.post("/{invoice_id}/send-email")
async def send_email(invoice_id: int, db: Session = Depends(get_db)):
    """(Re)send the invoice PDF by email."""
    inv = db.query(models.Invoice).filter_by(id=invoice_id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")

    from invoice.email_sender import send_invoice_email
    ok = await send_invoice_email(invoice_id, db)
    if not ok:
        raise HTTPException(500, "Email could not be sent – check SMTP settings")
    db.refresh(inv)
    return {"detail": "Email sent", "email_to": inv.email_to}


@router.post("/{invoice_id}/mark-paid", response_model=schemas.InvoiceRecordOut)
def mark_paid(invoice_id: int, db: Session = Depends(get_db)):
    inv = db.query(models.Invoice).filter_by(id=invoice_id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    inv.status = "PAID"
    inv.paid_at = _utcnow()
    db.commit()
    db.refresh(inv)
    return inv


@router.post("/{invoice_id}/regenerate-pdf", response_model=schemas.InvoiceRecordOut)
def regenerate_pdf(invoice_id: int, db: Session = Depends(get_db)):
    """Force-regenerate the PDF (useful after company settings change)."""
    inv = db.query(models.Invoice).filter_by(id=invoice_id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    try:
        from invoice.generator import generate_invoice_pdf
        generate_invoice_pdf(invoice_id, db)
        db.refresh(inv)
    except Exception as e:
        raise HTTPException(500, f"PDF generation failed: {e}")
    return inv
