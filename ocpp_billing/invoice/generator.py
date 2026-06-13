"""
PDF invoice generator – German §14 UStG compliant.
Produces an A4 invoice with company letterhead, itemized billing, VAT breakdown,
CO2 savings info, and IBAN payment instructions.
"""

import logging
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
)

from database import SessionLocal
import models

logger = logging.getLogger("invoice.generator")

OUTPUT_DIR = Path(__file__).parent.parent / "invoices"

BLUE = colors.HexColor("#1D4ED8")
BLUE_LIGHT = colors.HexColor("#EFF6FF")
GREEN_LIGHT = colors.HexColor("#F0FDF4")
GREEN = colors.HexColor("#16A34A")
GRAY = colors.HexColor("#6B7280")
GRAY_LIGHT = colors.HexColor("#F9FAFB")
GRAY_BORDER = colors.HexColor("#E5E7EB")


def _get_setting(db, key: str, default: str = "") -> str:
    s = db.query(models.SystemSettings).filter_by(key=key).first()
    return s.value if s else default


def _eur(amount: float) -> str:
    formatted = f"{abs(amount):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted} €"


def _kwh(v: float) -> str:
    return f"{v:.3f} kWh"


def generate_invoice_pdf(invoice_id: int, db=None) -> str:
    """
    Generate a PDF for the given invoice ID.
    Returns the absolute file path of the generated PDF.
    """
    close_db = db is None
    if db is None:
        db = SessionLocal()

    try:
        invoice = db.query(models.Invoice).filter_by(id=invoice_id).first()
        if not invoice:
            raise ValueError(f"Invoice {invoice_id} not found")

        session = invoice.session
        customer = invoice.customer or (session.customer if session else None)
        tariff = session.tariff if session else None

        # Company settings
        co_name    = _get_setting(db, "company_name", "Charging Station GmbH")
        co_address = _get_setting(db, "company_address", "Musterstraße 1\n12345 Musterstadt")
        co_taxno   = _get_setting(db, "company_tax_number", "")
        co_vatid   = _get_setting(db, "company_vat_id", "")
        co_iban    = _get_setting(db, "company_iban", "")
        co_bic     = _get_setting(db, "company_bic", "")
        co_bank    = _get_setting(db, "company_bank", "")
        co_phone   = _get_setting(db, "company_phone", "")
        co_email   = _get_setting(db, "company_email", "")
        co_web     = _get_setting(db, "company_website", "")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        pdf_path = OUTPUT_DIR / f"{invoice.invoice_number}.pdf"

        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            leftMargin=2*cm, rightMargin=2*cm,
            topMargin=2*cm, bottomMargin=2*cm,
        )

        styles = getSampleStyleSheet()
        base = styles["Normal"]
        h1    = ParagraphStyle("h1",    parent=base, fontSize=20, fontName="Helvetica-Bold", spaceAfter=2)
        h2    = ParagraphStyle("h2",    parent=base, fontSize=10, fontName="Helvetica-Bold", spaceAfter=2)
        n     = ParagraphStyle("n",     parent=base, fontSize=9,  spaceAfter=1)
        small = ParagraphStyle("small", parent=base, fontSize=7,  textColor=GRAY, spaceAfter=1)
        right = ParagraphStyle("right", parent=base, fontSize=9,  alignment=TA_RIGHT)
        bold  = ParagraphStyle("bold",  parent=base, fontSize=9,  fontName="Helvetica-Bold")
        center= ParagraphStyle("ctr",   parent=base, fontSize=9,  alignment=TA_CENTER)

        W = 17 * cm  # usable width

        elems = []

        # ── Header: title left, company right ─────────────────────────────────
        contact = " • ".join(filter(None, [co_phone, co_email, co_web]))
        company_block = (
            f"<b>{co_name}</b><br/>"
            + co_address.replace("\n", "<br/>")
            + (f"<br/><font size='7' color='#6B7280'>{contact}</font>" if contact else "")
        )
        header = Table(
            [[Paragraph("RECHNUNG", h1), Paragraph(company_block, right)]],
            colWidths=[9*cm, 8*cm],
        )
        header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        elems.append(header)
        elems.append(HRFlowable(width="100%", thickness=1.5, color=BLUE, spaceAfter=6))

        # ── Address + meta ────────────────────────────────────────────────────
        sender_line = f"<font size='6' color='gray'>{co_name} • {co_address.replace(chr(10), ', ')}</font>"

        if customer:
            addr_lines = []
            if customer.company:
                addr_lines.append(f"<b>{customer.company}</b>")
            addr_lines.append(customer.name)
            if customer.vat_id:
                addr_lines.append(f"USt-IdNr: {customer.vat_id}")
            if customer.address:
                addr_lines.extend(customer.address.split("\n"))
            recipient = sender_line + "<br/>" + "<br/>".join(addr_lines)
        else:
            recipient = sender_line + "<br/>Gast (ohne Kundenkonto)"

        inv_date = invoice.invoice_date.strftime("%d.%m.%Y") if invoice.invoice_date else "-"
        due_date = invoice.due_date.strftime("%d.%m.%Y") if invoice.due_date else "-"
        if session and session.end_time:
            svc_date = session.end_time.strftime("%d.%m.%Y")
        elif session and session.start_time:
            svc_date = session.start_time.strftime("%d.%m.%Y")
        else:
            svc_date = inv_date

        meta_rows = [
            [Paragraph("<b>Rechnungsnummer</b>", n), Paragraph(invoice.invoice_number, bold)],
            [Paragraph("Rechnungsdatum", small),     Paragraph(inv_date, n)],
            [Paragraph("Leistungsdatum", small),     Paragraph(svc_date, n)],
            [Paragraph("Fällig bis", small),    Paragraph(f"<b>{due_date}</b>", bold)],
        ]
        meta = Table(meta_rows, colWidths=[4*cm, 4.5*cm])
        meta.setStyle(TableStyle([
            ("TOPPADDING",    (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("BACKGROUND",    (0, 0), (-1, 0), BLUE_LIGHT),
            ("BOX",           (0, 0), (-1, -1), 0.5, GRAY_BORDER),
        ]))

        addr_meta = Table(
            [[Paragraph(recipient, n), meta]],
            colWidths=[9*cm, 8*cm],
        )
        addr_meta.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        elems.append(addr_meta)
        elems.append(Spacer(1, 8*mm))

        # ── Line items ─────────────────────────────────────────────────────────
        cp_label = ""
        if session and session.charge_point:
            cp_label = f" – Station: {session.charge_point.charge_point_id}"
        time_range = ""
        if session and session.start_time:
            time_range = session.start_time.strftime("%d.%m.%Y %H:%M")
            if session.end_time:
                time_range += " – " + session.end_time.strftime("%H:%M Uhr")

        COL = [0.7*cm, 7.8*cm, 2.3*cm, 2.3*cm, 2.7*cm]
        item_rows = [[
            Paragraph("Pos.", bold),
            Paragraph("Leistungsbeschreibung", bold),
            Paragraph("Menge", bold),
            Paragraph("Einzel€", bold),
            Paragraph("Gesamt", bold),
        ]]

        pos = 1
        if session and session.cost_connection > 0:
            item_rows.append([
                str(pos),
                Paragraph(f"Anschlussgebühr{cp_label}", n),
                "1",
                _eur(session.cost_connection),
                _eur(session.cost_connection),
            ])
            pos += 1

        if session and (session.energy_kwh or 0) > 0:
            ep = tariff.price_per_kwh if tariff else 0.0
            desc = f"Elektrische Energie{cp_label}"
            if time_range:
                desc += f"<br/><font size='7' color='gray'>{time_range}</font>"
            item_rows.append([
                str(pos),
                Paragraph(desc, n),
                _kwh(session.energy_kwh),
                f"{ep:.4f} €/kWh",
                _eur(session.cost_energy),
            ])
            pos += 1

        if session and (session.cost_time or 0) > 0:
            ep = tariff.price_per_minute if tariff else 0.0
            item_rows.append([
                str(pos),
                Paragraph("Ladezeit", n),
                f"{session.charging_minutes:.1f} min",
                f"{ep:.4f} €/min",
                _eur(session.cost_time),
            ])
            pos += 1

        if session and (session.cost_blocking or 0) > 0:
            ep = tariff.blocking_fee_per_minute if tariff else 0.0
            grace = tariff.blocking_grace_period_minutes if tariff else 0
            item_rows.append([
                str(pos),
                Paragraph(f"Blockiergebühr (>{grace} min Freikontingent)", n),
                f"{session.blocking_minutes:.1f} min",
                f"{ep:.4f} €/min",
                _eur(session.cost_blocking),
            ])
            pos += 1

        if pos == 1:
            item_rows.append(["1", Paragraph("Ladevorgang", n), "1", "0,00 €", "0,00 €"])

        row_bg = [colors.white, GRAY_LIGHT]
        items_tbl = Table(item_rows, colWidths=COL)
        items_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), BLUE),
            ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 9),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ALIGN",         (2, 0), (-1, -1), "RIGHT"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), row_bg),
            ("LINEBELOW",     (0, -1), (-1, -1), 0.75, BLUE),
            ("BOX",           (0, 0), (-1, -1), 0.5, GRAY_BORDER),
        ]))
        elems.append(items_tbl)
        elems.append(Spacer(1, 5*mm))

        # ── VAT totals ─────────────────────────────────────────────────────────
        vat_pct = f"{invoice.vat_rate * 100:.0f}%"
        totals = [
            ["Nettobetrag:",         _eur(invoice.amount_net)],
            [f"MwSt. {vat_pct}:",   _eur(invoice.vat_amount)],
            ["Gesamtbetrag (brutto):", _eur(invoice.amount_gross)],
        ]
        tot_tbl = Table(totals, colWidths=[5.5*cm, 3*cm], hAlign="RIGHT")
        tot_tbl.setStyle(TableStyle([
            ("FONTSIZE",      (0, 0), (-1, -1), 9),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ALIGN",         (1, 0), (1, -1), "RIGHT"),
            ("LINEABOVE",     (0, 1), (-1, 1), 0.5, GRAY),
            ("LINEABOVE",     (0, 2), (-1, 2), 1,   BLUE),
            ("BACKGROUND",    (0, 2), (-1, 2), BLUE),
            ("TEXTCOLOR",     (0, 2), (-1, 2), colors.white),
            ("FONTNAME",      (0, 2), (-1, 2), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 2), (-1, 2), 10),
            ("TOPPADDING",    (0, 2), (-1, 2), 5),
            ("BOTTOMPADDING", (0, 2), (-1, 2), 5),
        ]))
        elems.append(tot_tbl)
        elems.append(Spacer(1, 6*mm))

        # ── CO2 savings ────────────────────────────────────────────────────────
        if (invoice.co2_saved_kg or 0) > 0:
            co2_txt = (
                f"Umweltbeitrag: Mit diesem Ladevorgang haben Sie ca. "
                f"<b>{invoice.co2_saved_kg:.2f} kg CO₂</b> eingespart "
                f"im Vergleich zu einem vergleichbaren Verbrennerfahrzeug."
            )
            co2_box = Table([[Paragraph(co2_txt, small)]], colWidths=[W])
            co2_box.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), GREEN_LIGHT),
                ("BOX",           (0, 0), (-1, -1), 0.75, GREEN),
                ("TOPPADDING",    (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ]))
            elems.append(co2_box)
            elems.append(Spacer(1, 6*mm))

        # ── Payment instructions ───────────────────────────────────────────────
        if co_iban:
            elems.append(HRFlowable(width="100%", thickness=0.5, color=GRAY_BORDER))
            elems.append(Spacer(1, 3*mm))
            elems.append(Paragraph("Zahlungshinweis", h2))
            elems.append(Paragraph(
                f"Bitte überweisen Sie den Betrag von <b>{_eur(invoice.amount_gross)}</b> "
                f"bis zum <b>{due_date}</b> unter Angabe der Rechnungsnummer "
                f"<b>{invoice.invoice_number}</b> auf folgendes Konto:",
                n,
            ))
            elems.append(Spacer(1, 2*mm))

            bank_rows = [[co_name, ""]]
            if co_bank:
                bank_rows.append(["Bank:", co_bank])
            bank_rows.append(["IBAN:", co_iban])
            if co_bic:
                bank_rows.append(["BIC:", co_bic])
            bank_rows.append(["Verwendungszweck:", invoice.invoice_number])

            bank_tbl = Table(bank_rows, colWidths=[4*cm, W - 4*cm])
            bank_tbl.setStyle(TableStyle([
                ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE",      (0, 0), (-1, -1), 9),
                ("TOPPADDING",    (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("BACKGROUND",    (0, 0), (-1, -1), GRAY_LIGHT),
                ("BOX",           (0, 0), (-1, -1), 0.5, GRAY_BORDER),
                ("SPAN",          (0, 0), (-1, 0)),
                ("BACKGROUND",    (0, 0), (-1, 0), BLUE_LIGHT),
                ("FONTSIZE",      (0, 0), (-1, 0), 10),
            ]))
            elems.append(bank_tbl)
            elems.append(Spacer(1, 6*mm))

        # ── Footer ─────────────────────────────────────────────────────────────
        elems.append(HRFlowable(width="100%", thickness=0.5, color=GRAY_BORDER))
        elems.append(Spacer(1, 2*mm))
        footer_parts = [co_name]
        if co_vatid:
            footer_parts.append(f"USt-IdNr: {co_vatid}")
        if co_taxno:
            footer_parts.append(f"Steuernummer: {co_taxno}")
        elems.append(Paragraph(" • ".join(footer_parts), small))
        elems.append(Paragraph(
            "Diese Rechnung wurde elektronisch erstellt und ist ohne Unterschrift gültig.",
            small,
        ))

        doc.build(elems)

        invoice.pdf_path = str(pdf_path)
        db.commit()

        logger.info("Generated PDF: %s", pdf_path)
        return str(pdf_path)

    finally:
        if close_db:
            db.close()
