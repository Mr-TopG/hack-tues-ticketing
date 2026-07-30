import json
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import Lock
from xml.sax.saxutils import escape

import segno
from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .qr import ticket_check_in_url

PDF_FORMAT_VERSION = 1
PDF_FONT_NAME = "TicketDejaVu"
PDF_BOLD_FONT_NAME = "TicketDejaVuBold"
_FONT_REGISTRATION_LOCK = Lock()


def _register_fonts():
    if PDF_FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return

    with _FONT_REGISTRATION_LOCK:
        if PDF_FONT_NAME in pdfmetrics.getRegisteredFontNames():
            return

        regular_path = Path(settings.TICKET_PDF_FONT_PATH)
        bold_path = Path(settings.TICKET_PDF_BOLD_FONT_PATH)

        if not regular_path.is_file() or not bold_path.is_file():
            raise FileNotFoundError(
                "The configured ticket PDF fonts are unavailable."
            )

        pdfmetrics.registerFont(
            TTFont(PDF_FONT_NAME, str(regular_path))
        )
        pdfmetrics.registerFont(
            TTFont(PDF_BOLD_FONT_NAME, str(bold_path))
        )
        pdfmetrics.registerFontFamily(
            PDF_FONT_NAME,
            normal=PDF_FONT_NAME,
            bold=PDF_BOLD_FONT_NAME,
            italic=PDF_FONT_NAME,
            boldItalic=PDF_BOLD_FONT_NAME,
        )


def _local_datetime(value):
    return timezone.localtime(value).strftime(
        "%d %B %Y, %H:%M %Z"
    )


def build_ticket_pdf_source(ticket):
    event = ticket.category.event
    full_name = ticket.user.get_full_name().strip()

    return {
        "format_version": PDF_FORMAT_VERSION,
        "ticket_id": str(ticket.pk),
        "validation_token": ticket.validation_token,
        "status": ticket.status,
        "holder_name": full_name or ticket.user.email,
        "holder_email": ticket.user.email,
        "category_name": ticket.category.name,
        "event_name": event.name,
        "event_venue": event.venue,
        "event_status": event.status,
        "event_starts_at": event.starts_at.isoformat(),
        "event_ends_at": event.ends_at.isoformat(),
        "issued_at": ticket.issued_at.isoformat(),
        "check_in_url": ticket_check_in_url(
            ticket.validation_token
        ),
    }


def ticket_pdf_source_hash(source):
    payload = json.dumps(
        source,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _paragraph(value, style):
    return Paragraph(escape(str(value)), style)


def _qr_image(check_in_url):
    output = BytesIO()
    segno.make_qr(
        check_in_url,
        error="M",
    ).save(
        output,
        kind="png",
        scale=7,
        border=4,
        dark="#000000",
        light="#ffffff",
    )
    output.seek(0)
    return output


def render_ticket_pdf(source):
    _register_fonts()

    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Ticket {source['ticket_id']}",
        author="Hack TUES Tickets",
        subject="Event admission ticket",
    )
    base_styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TicketTitle",
        parent=base_styles["Title"],
        fontName=PDF_BOLD_FONT_NAME,
        fontSize=24,
        leading=29,
        textColor=colors.HexColor("#111827"),
        spaceAfter=7 * mm,
    )
    category_style = ParagraphStyle(
        "TicketCategory",
        parent=base_styles["Heading2"],
        fontName=PDF_BOLD_FONT_NAME,
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#2563eb"),
        alignment=TA_CENTER,
        spaceAfter=5 * mm,
    )
    body_style = ParagraphStyle(
        "TicketBody",
        parent=base_styles["BodyText"],
        fontName=PDF_FONT_NAME,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#1f2937"),
    )
    label_style = ParagraphStyle(
        "TicketLabel",
        parent=body_style,
        fontName=PDF_BOLD_FONT_NAME,
        textColor=colors.HexColor("#4b5563"),
    )
    note_style = ParagraphStyle(
        "TicketNote",
        parent=body_style,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#4b5563"),
        spaceBefore=4 * mm,
    )
    id_style = ParagraphStyle(
        "TicketId",
        parent=body_style,
        fontSize=8,
        leading=11,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#6b7280"),
    )

    details = (
        ("Attendee", source["holder_name"]),
        ("Email", source["holder_email"]),
        ("Venue", source["event_venue"] or "To be announced"),
        (
            "Starts",
            _local_datetime(
                datetime.fromisoformat(
                    source["event_starts_at"]
                )
            ),
        ),
        (
            "Ends",
            _local_datetime(
                datetime.fromisoformat(
                    source["event_ends_at"]
                )
            ),
        ),
    )
    detail_rows = [
        [
            _paragraph(label, label_style),
            _paragraph(value, body_style),
        ]
        for label, value in details
    ]
    detail_table = Table(
        detail_rows,
        colWidths=(34 * mm, 112 * mm),
        hAlign="CENTER",
    )
    detail_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, -1),
                    colors.HexColor("#f3f4f6"),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.HexColor("#d1d5db"),
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.25,
                    colors.HexColor("#e5e7eb"),
                ),
            ]
        )
    )

    qr_output = _qr_image(source["check_in_url"])
    qr_code = Image(
        qr_output,
        width=58 * mm,
        height=58 * mm,
    )
    qr_code.hAlign = "CENTER"

    story = [
        _paragraph(source["event_name"], title_style),
        _paragraph(source["category_name"], category_style),
        detail_table,
        Spacer(1, 8 * mm),
        KeepTogether(
            [
                qr_code,
                _paragraph(
                    (
                        "Present this QR code at the entrance. "
                        "It is personal and can be used only once."
                    ),
                    note_style,
                ),
                Spacer(1, 4 * mm),
                _paragraph(
                    f"Ticket ID: {source['ticket_id']}",
                    id_style,
                ),
            ]
        ),
    ]
    document.build(story)
    return output.getvalue()
