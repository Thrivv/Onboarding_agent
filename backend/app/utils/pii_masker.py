"""
app/utils/pii_masker.py
========================
Local, in-process PII masking for every document type this app extracts
(Emirates ID, Passport, Trade License, MOA, Ejari, BVI/Certificate of
Incorporation).

Adapted from a masking utility used in a different project (SQL payment
records — utr/ifsc/PAN/Aadhaar shaped). This version is rebuilt around this
project's actual field vocabulary, gathered directly from
app/services/ocr_service.py and each extractor under
app/services/specialized_ocr/. See backend/docs (PII masking plan artifact)
for the full per-document field tables and the reasoning behind each rule
below.

Six adaptations from the original utility, all applied here:
  1. Date of birth is explicitly classified as PII (the original utility's
     substring match on "date" would have wrongly preserved it).
  2. Company/trade/property names (company_name*, trade_name*, building_name,
     lessor_company, tenant_company, registered_agent, ...) are explicitly
     preserved via an entity-name allowlist, so they are never caught by the
     generic "name" pattern and hashed as if they were a person.
  3. MRZ lines (mrz_line1/mrz_line2) get a dedicated full-mask rule instead
     of relying on incidental free-text regex coverage.
  4. Regex patterns are UAE-shaped (Emirates ID 784-####-#######-#, UAE
     mobile numbers) instead of India-shaped (+91, PAN, Aadhaar) — the
     India-shaped patterns are kept too, for backward compatibility, but are
     no longer the only patterns available.
  5. Ejari's property/location identifiers (makani_number, plot_number,
     property_number) are explicitly preserved as business identifiers.
  6. Nationality fields are explicitly preserved everywhere (needed for
     AML/PEP/nationality-based compliance screening).

Field names in this codebase come in two shapes — "date_of_birth" from the
specialized extractors and "Date of Birth" from ocr_service.py's EID schema.
`_normalize()` collapses both to the same space-separated, lowercased form
so one set of patterns covers both.

Usage
-----
    from app.utils.pii_masker import mask_pii, mask_name

    masked = mask_pii(extracted_data, preserve_business_ids=True)
    masked_names = [mask_name(n) for n in member_names]   # bare name lists
"""

import re
import hashlib
import logging
from typing import Any, Dict, List, Union

logger = logging.getLogger(__name__)


def _normalize(field_name: str) -> str:
    """Lowercase and collapse '_'/'-' to spaces so 'date_of_birth' and
    'Date of Birth' (this app uses both conventions) match the same patterns."""
    return str(field_name).lower().replace('_', ' ').replace('-', ' ').strip()


# ── Entity / non-personal "name" fields (Fix #2) ─────────────────────────────
# Any field matching one of these is a business/property name, not a person,
# and must never be routed into the generic PERSON_<hash> name masking below.
ENTITY_NAME_PATTERNS = [
    'company name', 'trade name', 'building name', 'lessor company',
    'tenant company', 'registered agent', 'bank name', 'branch name',
]

# ── Nationality (Fix #6) — always preserved, needed for compliance screening ─
NATIONALITY_PATTERNS = ['nationality', 'country code']

# ── Business/registered addresses — distinct from a PERSONAL residence.
# Checked explicitly so the generic "address"/"location" exclusion below
# (which correctly flags a home address as PII) doesn't also catch the
# company's own registered address.
BUSINESS_ADDRESS_PATTERNS = [
    'company address', 'head office location', 'registered office',
]

# ── Date of birth (Fix #1) — explicit PII, never a preserved "business date" ─
DOB_PATTERNS = ['date of birth', 'dob']

# ── MRZ lines (Fix #3) — dedicated full mask ─────────────────────────────────
MRZ_PATTERNS = ['mrz line', 'mrz']

# ── Business identifiers preserved outright (incl. Fix #5, Ejari) ───────────
BUSINESS_PATTERNS = [
    # generic business/payment identifiers (kept for backward compatibility)
    'utr', 'rrn', 'reference', 'txn id', 'transaction id',
    'invoice', 'order id', 'po number', 'bill no',
    'amount', 'price', 'value', 'balance', 'total', 'currency',
    'timestamp', 'created at', 'updated at',
    'status', 'state', 'category',
    'company id', 'vendor id', 'customer id', 'supplier id',
    'product', 'item', 'sku', 'hsn',
    # dates — business/validity dates, not personal (date of birth is
    # excluded from this set explicitly, see DOB_PATTERNS / mask_pii below)
    'issue date', 'issuing date', 'expiry date', 'print date',
    'registration date', 'start date', 'end date', 'date of execution',
    'duration start date', 'appointment start', 'appointment renewal',
    'financial year start', 'financial year end', 'first financial year',
    'maximum duration', 'balance sheet submission', 'company duration',
    'incorporation date',
    # document/registration identifiers — needed for cross-document matching
    'license number', 'main license number', 'commercial register number',
    'receipt number', 'duns number', 'dcci number', 'contract number',
    'registration number', 'plot number', 'makani number', 'property number',
    'lessor license number', 'lessor license issuer',
    'tenant license', 'jurisdiction',
    # entity/financial terms — not personal data
    'legal type', 'company type', 'document type', 'page type',
    'number of shares', 'value per share', 'share type', 'payment status',
    'share percentage', 'share capital',
    'is agent', 'is direct ubo', 'ubo basis', 'source role', 'role',
    'area', 'property type', 'property subtype', 'usage', 'size',
    'sex',
]


def _is_entity_name(norm: str) -> bool:
    return any(p in norm for p in ENTITY_NAME_PATTERNS)


def _is_nationality(norm: str) -> bool:
    return any(p in norm for p in NATIONALITY_PATTERNS)


def _is_dob(norm: str) -> bool:
    return any(p == norm or p in norm for p in DOB_PATTERNS)


def _is_mrz(norm: str) -> bool:
    return any(p in norm for p in MRZ_PATTERNS)


def mask_pii(data: Any, preserve_business_ids: bool = True) -> Any:
    """
    Recursively mask PII in an extracted-document dict (or list of them)
    before it reaches an LLM prompt or a log line.

    Args:
        data: extractor output (dict, list, or scalar)
        preserve_business_ids: keep business/property/entity identifiers so
            cross-document matching and compliance screening keep working

    Returns:
        A new structure with PII fields replaced; business/company data,
        dates, and structural fields pass through unchanged.
    """
    if isinstance(data, list):
        return [mask_pii(item, preserve_business_ids) for item in data]

    if isinstance(data, dict):
        masked = {}
        for key, value in data.items():
            norm = _normalize(key)

            if preserve_business_ids and _is_business_identifier(norm):
                masked[key] = value
            elif _is_pii_field(norm):
                masked[key] = _mask_field_value(norm, value)
            else:
                masked[key] = mask_pii(value, preserve_business_ids)
        return masked

    if isinstance(data, str):
        return _mask_text_patterns(data)

    # Numbers, dates, booleans, None pass through
    return data


def _is_business_identifier(norm: str) -> bool:
    """
    True for fields that must be preserved: business/property identifiers,
    business dates, entity names, and nationality. False for personal names,
    date of birth, MRZ lines, contact details, and addresses — even though
    some of those fields' surface text might otherwise look like a business
    field (this ordering is what fixes Bug #1 and Bug #2).
    """
    # Entity names, business addresses, and nationality are always
    # preserved, checked first so they never fall through to the
    # personal-name / personal-address / PII checks below.
    if _is_entity_name(norm) or _is_nationality(norm):
        return True
    if any(p in norm for p in BUSINESS_ADDRESS_PATTERNS):
        return True

    # Explicit personal-data exclusions — must never be treated as a
    # preserved business field, regardless of what else they might match.
    if _is_dob(norm) or _is_mrz(norm):
        return False

    personal_exclusions = [
        'email', 'phone', 'mobile', 'contact', 'telephone',
        'address', 'street', 'location', 'residence',
        'pincode', 'zipcode', 'postal', 'pin code',
        'place of birth', 'place of issue',
        # personal name fields — note this deliberately does NOT use a bare
        # "name" substring check (that was the cause of Bug #2); each
        # personal-name field this project produces is listed explicitly.
        'owner name', 'manager name', 'customer name', 'holder name',
        'full name', 'beneficiary name', 'payer name', 'payee name',
        'user name', 'surname', 'given names', 'father name', 'mother name',
        'spouse name', 'name english', 'name arabic', 'member name',
        'passport number', 'old passport number', 'file number',
        'id number', 'account no', 'account number', 'acc no',
        'bank account', 'card number', 'card no',
        'owner number', 'tenant number',
        'pan', 'aadhar', 'aadhaar', 'ssn', 'tax id',
        'ifsc', 'swift', 'iban', 'ip address', 'device id', 'imei',
    ]
    if any(exc in norm for exc in personal_exclusions):
        return False

    return any(pattern in norm for pattern in BUSINESS_PATTERNS)


def _is_pii_field(norm: str) -> bool:
    """Identify PII fields by (normalized) name that must be masked."""
    if _is_dob(norm) or _is_mrz(norm):
        return True

    # Entity names / business addresses / nationality are never PII in this
    # classification (they are handled — preserved — by
    # _is_business_identifier before this is ever reached, but guard here
    # too in case this is called directly).
    if _is_entity_name(norm) or _is_nationality(norm):
        return False
    if any(p in norm for p in BUSINESS_ADDRESS_PATTERNS):
        return False

    pii_patterns = [
        'email', 'phone', 'mobile', 'contact', 'telephone',
        'account no', 'account number', 'acc no', 'bank account',
        'card number', 'card no',
        'pan', 'aadhar', 'aadhaar', 'ssn', 'tax id',
        'id number', 'passport number', 'old passport number', 'file number',
        'owner number', 'tenant number',
        'address', 'street', 'location', 'residence',
        'pincode', 'zipcode', 'postal', 'pin code',
        'place of birth', 'place of issue',
        'owner name', 'manager name', 'customer name', 'holder name',
        'full name', 'beneficiary name', 'payer name', 'payee name',
        'user name', 'surname', 'given names', 'father name', 'mother name',
        'spouse name', 'name english', 'name arabic', 'member name', 'name',
        'ifsc', 'swift', 'iban',
        'ip address', 'device id', 'imei',
    ]

    if norm in pii_patterns:
        return True

    for pattern in pii_patterns:
        if pattern in norm:
            # 'customer id'/'vendor id'/'supplier id' are business
            # identifiers, not the personal customer/vendor name.
            if norm.endswith(' id') and pattern in ('customer', 'vendor', 'supplier'):
                return False
            return True

    return False


_PARTIAL_ID_PATTERNS = [
    'id number', 'passport number', 'old passport number', 'file number',
    'account', 'card', 'owner number', 'tenant number',
]


def _mask_field_value(norm: str, value: Any) -> str:
    """Mask a single PII field's value based on its (normalized) field name."""
    if value is None or value == '':
        return value

    str_value = str(value)

    if _is_dob(norm):
        return '***DOB***'

    if _is_mrz(norm):
        return '***MRZ***'

    # Partial-mask identifiers: keep last 4 characters for audit correlation
    if any(p in norm for p in _PARTIAL_ID_PATTERNS):
        digits_or_chars = re.sub(r'[\s-]', '', str_value)
        if len(digits_or_chars) >= 4:
            return '****' + digits_or_chars[-4:]
        return '****'

    if 'email' in norm and '@' in str_value:
        try:
            local, domain = str_value.split('@', 1)
            if len(local) > 2:
                return f"{local[0]}***@{domain}"
            return f"***@{domain}"
        except Exception:
            return '***EMAIL***'

    if any(p in norm for p in ['phone', 'mobile', 'contact', 'telephone']):
        digits = re.sub(r'\D', '', str_value)
        if len(digits) >= 4:
            return '****' + digits[-4:]
        return '***PHONE***'

    # Personal names: consistent hash so repeated mentions of the same
    # person still correlate for the LLM / a reviewer, without exposing the
    # real name.
    name_patterns = [
        'owner name', 'manager name', 'customer name', 'holder name',
        'full name', 'beneficiary name', 'payer name', 'payee name',
        'user name', 'surname', 'given names', 'father name', 'mother name',
        'spouse name', 'name english', 'name arabic', 'member name', 'name',
    ]
    if any(p in norm for p in name_patterns):
        return mask_name(str_value)

    if any(p in norm for p in ['ifsc', 'swift', 'iban']):
        if len(str_value) > 4:
            return str_value[:4] + '****'
        return '****'

    if any(p in norm for p in ['pan', 'aadhar', 'aadhaar', 'ssn', 'tax id']):
        return '***MASKED***'

    if any(p in norm for p in ['address', 'street', 'location', 'residence',
                                'pincode', 'zipcode', 'postal', 'pin code',
                                'place of birth', 'place of issue']):
        return '***LOCATION***'

    return '***MASKED***'


def mask_name(value: Any) -> str:
    """
    Mask a bare person-name string outside of a dict context — e.g. a plain
    list of member/UBO names being logged (`[mask_name(n) for n in
    member_names]`). `mask_pii()` only classifies by dict field name, so a
    raw list of names never reaches `_mask_field_value`; this is the
    dedicated entry point for that case. Uses the same consistent hash as
    the dict-based name masking, so the same person masks to the same value
    either way.
    """
    if value is None or value == '':
        return value
    name_hash = hashlib.md5(str(value).encode()).hexdigest()[:8]
    return f"PERSON_{name_hash.upper()}"


# ── Free-text pattern masking (fallback for narrative/unstructured text) ────

_UAE_EID_RE = re.compile(r'\b784-?\d{4}-?\d{7}-?\d\b')
_UAE_MOBILE_RE = re.compile(r'\b(?:\+971[-\s]?)?0?5\d(?:[-\s]?\d){7}\b')
_INDIA_PHONE_RE = re.compile(r'\b(\+91[-\s]?)?[6-9]\d{9}\b')


def _mask_text_patterns(text: str) -> str:
    """Mask PII patterns in free text (narratives, descriptions, comments)."""
    if not isinstance(text, str) or not text:
        return text

    # Emirates ID — checked first (most specific) so its digits aren't
    # partially consumed by the generic long-digit-run pattern below.
    text = _UAE_EID_RE.sub(lambda m: '****' + re.sub(r'-', '', m.group(0))[-4:], text)

    # Email
    text = re.sub(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        '***EMAIL***',
        text
    )

    # UAE mobile (+971 5X ... / 05X ...)
    text = _UAE_MOBILE_RE.sub('***PHONE***', text)

    # India mobile — kept for backward compatibility with the source utility
    text = _INDIA_PHONE_RE.sub('***PHONE***', text)

    # PAN pattern (AAAAA9999A) — kept for backward compatibility
    text = re.sub(r'\b[A-Z]{5}[0-9]{4}[A-Z]\b', '***PAN***', text)

    # Aadhaar pattern (12 digits, sometimes with spaces) — kept for
    # backward compatibility
    text = re.sub(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', '***AADHAAR***', text)

    # IFSC pattern (AAAA0BBBBBB) — kept for backward compatibility
    text = re.sub(
        r'\b[A-Z]{4}0[A-Z0-9]{6}\b',
        lambda m: m.group(0)[:4] + '0****',
        text
    )

    # Credit card pattern (16 digits, optional spaces/dashes)
    text = re.sub(
        r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
        '****-****-****-****',
        text
    )

    # Generic long digit run (10-18 digits) — account-number-shaped free
    # text; runs last so more specific patterns above get first claim on
    # their digits.
    text = re.sub(
        r'\b\d{10,18}\b',
        lambda m: '****' + m.group(0)[-4:],
        text
    )

    # Pincode — only mask if preceded by "pincode"/"pin"/"postal"
    text = re.sub(
        r'(?i)(pincode|pin|postal)[\s:]+\d{6}\b',
        r'\1: ***PINCODE***',
        text
    )

    return text


# ── Stats / audit reporting (unchanged from the source utility — not field-
# specific, so none of the six fixes above apply here) ──────────────────────

def get_masking_stats(original_data: Any, masked_data: Any) -> Dict[str, int]:
    """Generate statistics about what was masked (for logging/audit)."""
    stats = {'total_fields': 0, 'masked_fields': 0, 'preserved_fields': 0}

    def count_fields(orig, masked):
        if isinstance(orig, dict) and isinstance(masked, dict):
            stats['total_fields'] += len(orig)
            for key in orig:
                if key in masked:
                    if orig[key] != masked[key]:
                        stats['masked_fields'] += 1
                    else:
                        stats['preserved_fields'] += 1
                    count_fields(orig[key], masked[key])
        elif isinstance(orig, list) and isinstance(masked, list):
            for o, m in zip(orig, masked):
                count_fields(o, m)

    count_fields(original_data, masked_data)
    return stats


def get_detailed_masking_report(original_data: Any, masked_data: Any, max_items: int = 3) -> Dict[str, Any]:
    """Generate a detailed field-level report of what was masked, for debugging."""
    report = {'stats': get_masking_stats(original_data, masked_data), 'field_changes': []}

    def find_changes(orig, masked, path=""):
        if len(report['field_changes']) >= max_items:
            return
        if isinstance(orig, dict) and isinstance(masked, dict):
            for key in orig:
                if key in masked:
                    current_path = f"{path}.{key}" if path else key
                    if orig[key] != masked[key]:
                        if not isinstance(orig[key], (dict, list)):
                            report['field_changes'].append({
                                'field': current_path,
                                'original': str(orig[key])[:50],
                                'masked': str(masked[key])[:50],
                                'type': type(orig[key]).__name__
                            })
                    else:
                        find_changes(orig[key], masked[key], current_path)
        elif isinstance(orig, list) and isinstance(masked, list):
            for idx, (o, m) in enumerate(zip(orig, masked)):
                find_changes(o, m, f"{path}[{idx}]")

    find_changes(original_data, masked_data)
    return report
