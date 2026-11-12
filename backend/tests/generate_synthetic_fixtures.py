"""
Generate synthetic (non-real, non-PII) fixture documents for the OCR corpus
harness (tests/ocr_corpus.py), so Layer 1 (text extraction) and Layer 2
(request shape / prompt size) can run against something instead of the empty
.gitkeep-only directories.

Every value below is fabricated for this purpose. Nothing here is a real
person, company, or document. Each fixture is padded past its extractor's
own raw_text truncation ceiling, so the recorded prompt reflects the
worst-case (ceiling-bound) size a real, longer document would also hit --
not a best-case short sample.
"""
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from pathlib import Path

FIXTURES = Path("tests/ocr_fixtures")

MARKER = "SYNTHETIC TEST FIXTURE -- NO REAL PERSON, COMPANY OR DOCUMENT -- GENERATED FOR THE OCR CORPUS BASELINE (PHASE 0)"


def write_pdf(path: Path, lines: list[str]) -> int:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    for line in lines:
        if line == "":
            pdf.ln(5)
        else:
            pdf.multi_cell(0, 5, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return path.stat().st_size


def filler_paragraphs(template: str, count: int) -> list[str]:
    return [template.format(n=i + 1) for i in range(count)]


# ---------------------------------------------------------------------------
# BVI Certificate of Incorporation -- ceiling: raw_text[:6000]
# ---------------------------------------------------------------------------
bvi_lines = [
    MARKER,
    "",
    "TERRITORY OF THE BRITISH VIRGIN ISLANDS",
    "BVI BUSINESS COMPANIES ACT, 2004",
    "CERTIFICATE OF INCORPORATION",
    "",
    "Company Name: SAMPLE HOLDINGS LIMITED",
    "Registration Number: BVI-0000001",
    "Jurisdiction: British Virgin Islands",
    "Incorporation Date: 01/01/2020",
    "Company Type: Business Company Limited by Shares",
    "Registered Agent: Sample Registered Agent Services Ltd.",
    "Registered Office: Sample Chambers, PO Box 0000, Road Town, Tortola, British Virgin Islands",
    "Authorised Share Capital: USD 50,000 divided into 50,000 shares of USD 1.00 each",
    "",
    "Directors and Shareholders:",
    "1. SAMPLE DIRECTOR ONE -- Director -- Nationality: Sample Country -- Shares: 0",
    "2. SAMPLE SHAREHOLDER TWO -- Shareholder -- Nationality: Sample Country -- Shares: 35,000 (70%)",
    "3. SAMPLE SHAREHOLDER THREE -- Director & Shareholder -- Nationality: Sample Country -- Shares: 15,000 (30%)",
    "",
]
bvi_lines += filler_paragraphs(
    "Clause {n}: This synthetic filler clause exists only to bring the fixture "
    "document up to a length comparable to a real, multi-page Certificate of "
    "Incorporation with attached registers, so the OCR corpus baseline "
    "measures a realistic worst-case prompt size rather than a short sample. "
    "No party, obligation, or right described in this clause is real.",
    40,
)

# ---------------------------------------------------------------------------
# Ejari tenancy contract -- ceiling: raw_text[:20000]
# ---------------------------------------------------------------------------
ejari_lines = [
    MARKER,
    "",
    "GOVERNMENT OF DUBAI -- DUBAI LAND DEPARTMENT",
    "EJARI -- TENANCY CONTRACT REGISTRATION CERTIFICATE",
    "",
    "Contract No: 0100000000000099",
    "Registration Date: 01-01-2025",
    "",
    "OWNER DETAILS",
    "Owner Name: SAMPLE OWNER NAME",
    "Owner Number: 100001",
    "Owner Nationality: United Arab Emirates",
    "",
    "LESSOR DETAILS",
    "Lessor Company: SAMPLE PROPERTY MANAGEMENT LLC",
    "Lessor License Number: 1000001",
    "Lessor License Issuer: DED-Dubai",
    "Lessor Phone: 971500000000",
    "Lessor Email: sample.lessor@example.invalid",
    "",
    "TENANT DETAILS",
    "Tenant Company: SAMPLE TENANT COMPANY LLC",
    "Tenant Number: 0400000000000099",
    "Tenant License: 1000002 / 01-01-2025",
    "Tenant License Issuer: DED-Dubai",
    "",
    "CONTRACT DETAILS",
    "Start Date: 01-01-2025",
    "End Date: 31-12-2025",
    "",
    "PROPERTY DETAILS",
    "Building Name: SAMPLE BUILDING",
    "Area: Sample District",
    "Plot Number: 000-000",
    "Makani Number: 00000 00000",
    "Property Number: 000-00",
    "Property Type: Office",
    "Property Subtype: Office",
    "Usage: Commercial",
    "Size: 100.00 Sq.m",
    "",
]
ejari_lines += filler_paragraphs(
    "Term {n}: This synthetic filler term exists only to bring the fixture "
    "document up to a length comparable to a real tenancy contract with its "
    "full schedule of standard terms and conditions, so the OCR corpus "
    "baseline measures a realistic worst-case prompt size. No party, "
    "premises, or obligation named here is real.",
    260,
)

# ---------------------------------------------------------------------------
# Memorandum of Association -- ceiling: raw_text[:20000]
# ---------------------------------------------------------------------------
moa_lines = [
    MARKER,
    "",
    "MEMORANDUM OF ASSOCIATION",
    "OF",
    "SAMPLE TRADING COMPANY L.L.C",
    "",
    "Company Name: SAMPLE TRADING COMPANY L.L.C",
    "Owner Name: Mr. SAMPLE OWNER NAME",
    "Passport Number: A0000000",
    "Date of Birth: 01/01/1990",
    "Company Duration: 99 years",
    "Legal Reserve Percentage: 10%",
    "Financial Year Start: 1st January",
    "",
]
moa_articles = [
    "ARTICLE 1 -- NAME: The name of the company is SAMPLE TRADING COMPANY L.L.C, a limited liability company.",
    "ARTICLE 2 -- OBJECTS: The objects for which the company is established are sample general trading activities.",
    "ARTICLE 3 -- DURATION: The duration of the company shall be 99 years from the date of its registration.",
    "ARTICLE 4 -- REGISTERED OFFICE: The registered office of the company shall be in Dubai, United Arab Emirates.",
    "ARTICLE 5 -- CAPITAL: The capital of the company is a sample amount divided into equal shares among the partners.",
    "ARTICLE 6 -- LEGAL RESERVE: Ten percent of the annual net profits shall be set aside as a legal reserve each year.",
    "ARTICLE 7 -- FINANCIAL YEAR: The financial year of the company shall commence on the 1st of January each year.",
    "ARTICLE 8 -- MANAGEMENT: The company shall be managed by one or more managers appointed by the partners.",
]
for i in range(180):
    moa_lines.append(f"{moa_articles[i % len(moa_articles)]} (restated at clause {i + 9} for length.)")

# ---------------------------------------------------------------------------
# Trade License (multi-owner) -- ceiling: raw_text[:25000]
# ---------------------------------------------------------------------------
trade_lines = [
    MARKER,
    "",
    "DEPARTMENT OF ECONOMY AND TOURISM -- DUBAI",
    "TRADE LICENSE",
    "",
    "License No: 1000001",
    "Company Name: SAMPLE GENERAL TRADING L.L.C",
    "Name: SAMPLE GENERAL TRADING",
    "Legal Type: LIMITED LIABILITY COMPANY",
    "Issue Date: 01/01/2024",
    "Expiry Date: 31/12/2026",
    "",
    "License Members",
    "1. SAMPLE MANAGER ONE -- Manager -- Nationality: Sample Country",
    "2. SAMPLE PARTNER TWO -- Partner -- Nationality: Sample Country -- Shares: 60%",
    "3. SAMPLE PARTNER THREE -- Partner -- Nationality: Sample Country -- Shares: 40%",
    "",
    "Partners Annex",
    "1. SAMPLE PARTNER TWO -- Nationality: Sample Country -- Shares: 60.0000000%",
    "2. SAMPLE PARTNER THREE -- Nationality: Sample Country -- Shares: 40.0000000%",
    "3. SAMPLE AGENT FOUR -- Local Service Agent -- Nationality: Sample Country",
    "",
]
trade_lines += filler_paragraphs(
    "Condition {n}: This synthetic filler condition exists only to bring the "
    "fixture document up to a length comparable to a real trade license with "
    "its full schedule of activities and standard conditions, so the OCR "
    "corpus baseline measures a realistic worst-case prompt size. No party "
    "or activity named here is real.",
    300,
)

FIXTURES_MAP = {
    "bvi": bvi_lines,
    "ejari": ejari_lines,
    "moa": moa_lines,
    "trade": trade_lines,
}

if __name__ == "__main__":
    for doc_type, lines in FIXTURES_MAP.items():
        out = FIXTURES / doc_type / "synthetic_sample_01.pdf"
        size = write_pdf(out, lines)
        print(f"{doc_type:8s} -> {out}  ({size} bytes, {len(lines)} lines)")
