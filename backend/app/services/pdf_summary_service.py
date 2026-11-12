# backend/app/services/pdf_summary_service.py
"""
Generates a professional onboarding summary PDF for corporate banking accounts.
Includes: FATCA details, all members (with UBO/AS/Member roles), uploaded documents,
verification status, and submission timestamp.
"""

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.platypus.flowables import HRFlowable
from app import config


# ── Brand colours ──────────────────────────────────────────────────────────────
BRAND_PURPLE   = colors.HexColor("#7C3AED")   # indigo-600
BRAND_INDIGO   = colors.HexColor("#4338CA")   # indigo-700
BRAND_DARK     = colors.HexColor("#1E1B4B")   # very dark indigo
SECTION_BG     = colors.HexColor("#F5F3FF")   # purple-50
ROW_ALT        = colors.HexColor("#F8F8FF")
GREEN_TEXT     = colors.HexColor("#15803D")
AMBER_TEXT     = colors.HexColor("#B45309")
RED_TEXT       = colors.HexColor("#B91C1C")
GRAY_TEXT      = colors.HexColor("#6B7280")
BORDER_COLOR   = colors.HexColor("#DDD6FE")   # purple-200
UBO_COLOR      = colors.HexColor("#F59E0B")   # amber
AS_COLOR       = colors.HexColor("#7C3AED")   # purple
MEMBER_COLOR   = colors.HexColor("#6B7280")   # gray

# ── Display-label mapping ────────────────────────────────────────────────────
# The stored `account_type` / `ownership_type` DB values are unchanged
# ("Corporate", "Single Owner", "Partnership", "Multiple Owners") — this only
# maps them to friendlier labels for anything the applicant actually reads.
_ACCOUNT_TYPE_DISPLAY = {
    "Corporate": "Business",
}
_OWNERSHIP_TYPE_DISPLAY = {
    "Single Owner": "Sole Proprietorship",
    "Partnership": "Joint Ownership",
    "Multiple Owners": "Joint Ownership",
}


def _display_account_type(value: str) -> str:
    return _ACCOUNT_TYPE_DISPLAY.get(value, value or "—")


def _display_ownership_type(value: str) -> str:
    return _OWNERSHIP_TYPE_DISPLAY.get(value, value or "—")


def _styles():
    base = getSampleStyleSheet()
    custom = {
        "Title": ParagraphStyle(
            "Title", parent=base["Normal"],
            fontSize=20, textColor=BRAND_DARK, spaceAfter=4,
            fontName="Helvetica-Bold", alignment=TA_LEFT,
        ),
        "Subtitle": ParagraphStyle(
            "Subtitle", parent=base["Normal"],
            fontSize=11, textColor=BRAND_PURPLE, spaceAfter=2,
            fontName="Helvetica", alignment=TA_LEFT,
        ),
        "SectionHeader": ParagraphStyle(
            "SectionHeader", parent=base["Normal"],
            fontSize=10, textColor=BRAND_DARK, spaceBefore=14, spaceAfter=6,
            fontName="Helvetica-Bold",
            borderPad=4,
        ),
        "Label": ParagraphStyle(
            "Label", parent=base["Normal"],
            fontSize=8, textColor=GRAY_TEXT, fontName="Helvetica-Bold",
            spaceAfter=1,
        ),
        "Value": ParagraphStyle(
            "Value", parent=base["Normal"],
            fontSize=9, textColor=BRAND_DARK, fontName="Helvetica",
            spaceAfter=3,
        ),
        "Small": ParagraphStyle(
            "Small", parent=base["Normal"],
            fontSize=7.5, textColor=GRAY_TEXT, fontName="Helvetica",
        ),
        "Footer": ParagraphStyle(
            "Footer", parent=base["Normal"],
            fontSize=7, textColor=GRAY_TEXT, fontName="Helvetica",
            alignment=TA_CENTER,
        ),
        "Normal": base["Normal"],
    }
    return custom


def _section(title: str, styles) -> list:
    """Returns a section header with a rule below it."""
    return [
        Paragraph(title, styles["SectionHeader"]),
        HRFlowable(width="100%", thickness=1, color=BORDER_COLOR, spaceAfter=6),
    ]


def _kv_table(rows: list, styles) -> Table:
    """Two-column label/value table for details."""
    data = []
    for label, value in rows:
        data.append([
            Paragraph(label, styles["Label"]),
            Paragraph(str(value) if value else "—", styles["Value"]),
        ])
    t = Table(data, colWidths=[5 * cm, 12 * cm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def _role_pill(label: str, colour) -> str:
    """Simple text badge (no background in PDF — just coloured bold text)."""
    return f'<font color="{colour.hexval()}" name="Helvetica-Bold">[{label}]</font>'


def generate_onboarding_summary_pdf(
    email: str,
    user_data: dict,
    fatca_data: Optional[dict],
    fatca_status: str,
    ki_list: List[dict],
    uploaded_docs: List[dict],
    package_data: Optional[dict] = None,
) -> bytes:
    """
    Generate a full onboarding summary PDF and return the raw bytes.

    Args:
        email: User email
        user_data: User registration dict from Supabase
        fatca_data: FATCA form fields dict (None if not filled)
        fatca_status: 'not_started' | 'not_applicable' | 'completed'
        ki_list: List of key individual dicts
        uploaded_docs: List of uploaded document dicts
        package_data: Product package selection dict (None if not selected)

    Returns:
        PDF bytes
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="Onboarding Summary — MyBank",
    )

    st = _styles()
    story = []
    now_str = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")
    page_w = A4[0] - 4 * cm   # usable width

    # ── HEADER ─────────────────────────────────────────────────────────────────
    header_data = [[
        Paragraph("MyBank / Thrivv", st["Title"]),
        Paragraph(f"Generated: {now_str}", st["Small"]),
    ]]
    header_t = Table(header_data, colWidths=[12 * cm, 5 * cm])
    header_t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    story.append(header_t)
    story.append(Paragraph("Account Onboarding Summary", st["Subtitle"]))
    story.append(HRFlowable(width="100%", thickness=2, color=BRAND_PURPLE, spaceBefore=4, spaceAfter=10))

    # ── APPLICANT DETAILS ──────────────────────────────────────────────────────
    story += _section("1. Applicant Details", st)
    applicant_rows = [
        ("Full Name",       f"{user_data.get('first_name', '')} {user_data.get('last_name', '')}".strip()),
        ("Email",           email),
        ("Account Type",    _display_account_type(user_data.get("account_type", ""))),
        ("Ownership Type",  _display_ownership_type(user_data.get("ownership_type", ""))),
        ("Business Name",   user_data.get("business_name", "—")),
        ("Mobile",          user_data.get("mobile_number", "—")),
        ("Reference ID",    user_data.get("id", "—")),
    ]
    story.append(_kv_table(applicant_rows, st))

    # ── FATCA DECLARATION ──────────────────────────────────────────────────────
    story += _section("2. FATCA Declaration", st)
    fatca_label = {
        "completed":    "✔ Completed",
        "not_applicable": "N/A — Not Applicable",
        "not_started":  "⏳ Pending",
    }.get(fatca_status, fatca_status or "—")
    story.append(_kv_table([("Status", fatca_label)], st))

    if fatca_status == "completed" and fatca_data:
        fatca_fields = [
            ("Entity Type",               fatca_data.get("entity_type")),
            ("Country of Tax Residence",  fatca_data.get("country_of_tax_residence")),
            ("Incorporated in USA",       fatca_data.get("entity_incorporated_in_usa")),
            ("US Ownership",              fatca_data.get("entity_has_us_ownership")),
            ("US Address / Phone",        fatca_data.get("address_or_phone_in_usa")),
            ("Payment to USA",            fatca_data.get("payment_instruction_to_usa")),
            ("Income from US Sources",    fatca_data.get("income_from_us_sources")),
            ("IRS Form Obtained",         fatca_data.get("irs_form_obtained")),
            ("US Tax ID",                 fatca_data.get("us_tax_id")),
        ]
        visible = [(l, v) for l, v in fatca_fields if v and v not in ("null", "undefined", "None")]
        if visible:
            story.append(Spacer(1, 4))
            story.append(_kv_table(visible, st))
    elif fatca_status == "not_applicable":
        story.append(Paragraph(
            "FATCA declared as Not Applicable for this account.",
            st["Small"]
        ))

    # ── PRODUCT PACKAGE SELECTION ──────────────────────────────────────────────
    story += _section("3. Product Package Selection", st)
    if package_data and package_data.get("selected_package"):
        _pkg_name     = package_data.get("selected_package", "—")
        _pkg_products = package_data.get("availed_products") or []
        story.append(_kv_table([("Package", _pkg_name)], st))
        if _pkg_products:
            story.append(Spacer(1, 4))
            story.append(Paragraph("Availed Products:", st["Label"]))
            story.append(Spacer(1, 2))
            for _p in _pkg_products:
                story.append(Paragraph(f"  • {_p}", st["Small"]))
    else:
        story.append(Paragraph("No product package selected.", st["Small"]))

    # ── MEMBERS / KEY INDIVIDUALS ──────────────────────────────────────────────
    story += _section("4. Members & Key Individuals", st)

    if not ki_list:
        story.append(Paragraph("No members declared.", st["Small"]))
    else:
        # Table header
        col_w = [0.6 * cm, 5.8 * cm, 3.2 * cm, 2.4 * cm, 2.2 * cm, 2.8 * cm]
        header_row = [
            Paragraph("#", st["Label"]),
            Paragraph("Name", st["Label"]),
            Paragraph("Role", st["Label"]),
            Paragraph("ID Type", st["Label"]),
            Paragraph("Source", st["Label"]),
            Paragraph("Verification", st["Label"]),
        ]
        rows = [header_row]

        for i, ki in enumerate(ki_list):
            name = ki.get("display_name") or f"{ki.get('first_name','')} {ki.get('last_name','')}".strip()
            # Build role
            role_parts = []
            if ki.get("is_ubo"):
                role_parts.append("UBO")
            if ki.get("is_authorised_signatory"):
                role_parts.append("AS")
            if not role_parts:
                role_parts.append("Member")
            role_str = " & ".join(role_parts)

            # Role colour
            if "UBO" in role_parts and "AS" in role_parts:
                role_col = UBO_COLOR
            elif "UBO" in role_parts:
                role_col = UBO_COLOR
            elif "AS" in role_parts:
                role_col = AS_COLOR
            else:
                role_col = MEMBER_COLOR

            v_status = ki.get("verification_status", "pending")
            v_colour = GREEN_TEXT if v_status == "verified" else (RED_TEXT if v_status == "failed" else AMBER_TEXT)

            source = ki.get("source", "")
            source_label = "MOA" if source == "MOA_EXTRACTED" else "Added"

            rows.append([
                Paragraph(str(i + 1), st["Small"]),
                Paragraph(name or "—", st["Value"]),
                Paragraph(f'<font color="{role_col.hexval()}">{role_str}</font>', st["Value"]),
                Paragraph(ki.get("id_type") or "—", st["Small"]),
                Paragraph(source_label, st["Small"]),
                Paragraph(f'<font color="{v_colour.hexval()}">{v_status.capitalize()}</font>', st["Small"]),
            ])

        members_t = Table(rows, colWidths=col_w, repeatRows=1)
        members_t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), SECTION_BG),
            ("TEXTCOLOR",  (0, 0), (-1, 0), BRAND_DARK),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, 0), 8),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
            ("GRID",       (0, 0), (-1, -1), 0.4, BORDER_COLOR),
            ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
            ("TOPPADDING",    (0, 1), (-1, -1), 4),
        ]))
        story.append(members_t)

    # ── KI CONTACT DETAILS (AI_ADDED KIs only) ────────────────────────────────
    # Only show this section when at least one KI has contact info collected
    # via the conversational loop (system_role / contact_email / phone_number).
    _ki_with_contact = [
        ki for ki in ki_list
        if ki.get("system_role") or ki.get("contact_email") or ki.get("phone_number")
    ]
    if _ki_with_contact:
        story += _section("4a. Key Individual Contact Details", st)
        _ci_col_w = [0.6 * cm, 4.8 * cm, 3.0 * cm, 4.8 * cm, 3.8 * cm]
        _ci_header = [
            Paragraph("#",             st["Label"]),
            Paragraph("Name",          st["Label"]),
            Paragraph("System Role",   st["Label"]),
            Paragraph("Contact Email", st["Label"]),
            Paragraph("Phone",         st["Label"]),
        ]
        _ci_rows = [_ci_header]
        for _ci_i, _ci_ki in enumerate(_ki_with_contact, 1):
            _ci_name  = _ci_ki.get("display_name") or f"{_ci_ki.get('first_name','')} {_ci_ki.get('last_name','')}".strip()
            _ci_rows.append([
                Paragraph(str(_ci_i),                              st["Small"]),
                Paragraph(_ci_name or "—",                         st["Value"]),
                Paragraph(_ci_ki.get("system_role")   or "—",     st["Small"]),
                Paragraph(_ci_ki.get("contact_email") or "—",     st["Small"]),
                Paragraph(_ci_ki.get("phone_number")  or "—",     st["Small"]),
            ])
        _ci_t = Table(_ci_rows, colWidths=_ci_col_w, repeatRows=1)
        _ci_t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), SECTION_BG),
            ("TEXTCOLOR",     (0, 0), (-1, 0), BRAND_DARK),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, 0), 8),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, ROW_ALT]),
            ("GRID",          (0, 0), (-1, -1), 0.4, BORDER_COLOR),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
            ("TOPPADDING",    (0, 1), (-1, -1), 4),
        ]))
        story.append(_ci_t)

    # ── UPLOADED DOCUMENTS ─────────────────────────────────────────────────────
    story += _section("5. Uploaded Documents", st)

    if not uploaded_docs:
        story.append(Paragraph("No documents on record.", st["Small"]))
    else:
        doc_header = [
            Paragraph("#", st["Label"]),
            Paragraph("Document Type", st["Label"]),
            Paragraph("Status", st["Label"]),
            Paragraph("Uploaded", st["Label"]),
        ]
        doc_rows = [doc_header]
        for i, d in enumerate(uploaded_docs):
            doc_type = str(d.get("document_type") or d.get("type") or "—").replace("_", " ").title()
            status = str(d.get("status") or "—")
            s_colour = GREEN_TEXT if "valid" in status.lower() or "verified" in status.lower() else (
                RED_TEXT if "invalid" in status.lower() or "reject" in status.lower() else AMBER_TEXT
            )
            created = d.get("created_at") or d.get("uploaded_at") or ""
            if created:
                try:
                    created = datetime.fromisoformat(created.replace("Z", "+00:00")).strftime("%d %b %Y")
                except Exception:
                    pass

            doc_rows.append([
                Paragraph(str(i + 1), st["Small"]),
                Paragraph(doc_type, st["Value"]),
                Paragraph(f'<font color="{s_colour.hexval()}">{status.capitalize()}</font>', st["Small"]),
                Paragraph(str(created) if created else "—", st["Small"]),
            ])

        docs_t = Table(doc_rows, colWidths=[0.6 * cm, 7 * cm, 4 * cm, 5.4 * cm], repeatRows=1)
        docs_t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), SECTION_BG),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, 0), 8),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, ROW_ALT]),
            ("GRID",          (0, 0), (-1, -1), 0.4, BORDER_COLOR),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
            ("TOPPADDING",    (0, 1), (-1, -1), 4),
        ]))
        story.append(docs_t)

    # ── DECLARATION ────────────────────────────────────────────────────────────
    story += _section("6. Self-Declaration", st)
    decl_path = Path(config.USER_DOCS_BASE) / email / "self_declaration.json"
    decl_confirmed = False
    decl_time = "—"
    if decl_path.exists():
        import json as _json
        try:
            with open(decl_path) as f:
                decl_data = _json.load(f)
            decl_confirmed = True
            raw_ts = decl_data.get("confirmed_at", "")
            if raw_ts:
                decl_time = datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).strftime("%d %B %Y, %H:%M UTC")
        except Exception:
            pass

    story.append(_kv_table([
        ("Confirmed",      "Yes" if decl_confirmed else "No"),
        ("Confirmed At",   decl_time),
    ], st))

    if decl_confirmed:
        story.append(Spacer(1, 6))
        declaration_text = (
            "I confirm that all information and documents submitted during this onboarding process "
            "are accurate, complete, and truthful to the best of my knowledge. I understand that "
            "providing false information may result in rejection of my application."
        )
        story.append(Paragraph(declaration_text, ParagraphStyle(
            "DeclText", parent=st["Small"],
            borderPad=8, backColor=colors.HexColor("#F0FDF4"),
            borderColor=colors.HexColor("#BBF7D0"), borderWidth=1,
            fontSize=8, leading=12,
        )))

    # ── FOOTER ─────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY_TEXT, spaceAfter=6))
    story.append(Paragraph(
        f"MyBank / Thrivv Banking · Onboarding Summary · Generated {now_str} · CONFIDENTIAL",
        st["Footer"]
    ))

    doc.build(story)
    buf.seek(0)
    return buf.read()
