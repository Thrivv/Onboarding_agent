"""
app/services/textract_id_client.py
====================================
AWS Textract AnalyzeID client for identity documents.

prompt-remediation Phase 1, item #4: replaces sending an identity-document
image to a general-purpose vision LLM with Amazon Textract's AnalyzeID API,
which extracts structured fields without the image ever leaving AWS's
boundary to a third-party model provider. This is the change already
flagged as a TODO in app/services/image_redaction_service.py's own
docstring ("DO NOT put [pixel redaction] in front of the primary
EID/Passport extraction call ... The fix there is to stop sending the
image to a third-party LLM at all: call Textract AnalyzeID instead") and
designed in dumps/docs/architecture/pii-masking-guardrails.md §7.2.

FEATURE FLAG: config.TEXTRACT_ANALYZE_ID_ENABLED (default False). Off by
default so this ships mergeable without live AWS Textract IAM permissions
configured in every environment. boto3 is imported lazily inside
_textract_client() -- this module never hard-fails to import just because
boto3 or AWS credentials are not resolvable in a given environment.

COVERAGE CAVEAT: AWS Textract's AnalyzeID is documented as supporting U.S.
driver's licenses/state IDs and passports; it is not documented as
officially supporting UAE Emirates ID cards specifically. This module is
therefore wired into the standalone passport pipeline
(specialized_ocr/passport_extractor.py) first, where AnalyzeID's own
"PASSPORT" ID_TYPE gives a clearer coverage signal. EID extraction stays
on the existing vision-LLM path in ocr_service.py's shared multi-document
router until real (anonymized) UAE Emirates ID samples confirm usable
field coverage from AnalyzeID -- see the Phase 1 item #4 note in
prompt-remediation-plan.html for the full reasoning. Every call site using
this module must treat an insufficient/empty AnalyzeID result as a signal
to fall back to the vision-LLM path, never as ground truth that the
document has no data (see is_passport_result_sufficient below).

Also NOT applicable here: the "never mask the extraction call's own input"
rule from bedrock-claude-pii-json-storage.md §7.1. That rule is about not
running PII *masking* on text before an extraction reads it. Sending the
image to Textract instead of a vision LLM is a different move entirely --
it is choosing which processor gets the real image, in favour of the one
that keeps it inside AWS's boundary rather than forwarding it to a
general-purpose model provider. Textract still receives, and must receive,
the real unmasked image to do its job.
"""

import logging
import os
import re
from datetime import datetime
from typing import Dict, Optional

from app import config

logger = logging.getLogger(__name__)

# Same env-var pattern as image_redaction_service.py, so both Textract
# call sites land on the same region without needing two separate
# settings -- me-central-1 (UAE) is the sensible default for data
# residency and Textract regional availability; override either the
# specific or the generic var if a deployment needs something else.
AWS_REGION = os.environ.get("TEXTRACT_AWS_REGION", os.environ.get("AWS_REGION", "me-central-1"))

_textract = None


class TextractUnavailable(Exception):
    """
    Raised whenever Textract AnalyzeID cannot be used for this call: the
    feature flag is off, boto3 isn't installed, AWS credentials aren't
    resolvable, or the API call itself failed. Callers catch this and fall
    back to the existing vision-LLM extraction path -- it is an expected,
    routine control-flow signal in an environment without Textract set up,
    not necessarily a bug.
    """


def _textract_client():
    global _textract
    if _textract is None:
        import boto3  # lazy import -- see module docstring
        _textract = boto3.client("textract", region_name=AWS_REGION)
    return _textract


def analyze_identity_document(image_bytes: bytes) -> Dict[str, str]:
    """
    Call Textract AnalyzeID on a single identity-document page image
    (JPEG/PNG bytes) and return its fields as a flat
    {Textract_field_type: value} dict, e.g. {"FIRST_NAME": "JOHN", ...}.

    Raises TextractUnavailable if the feature flag is off, boto3/AWS
    credentials aren't available, or the API call fails.
    """
    if not config.TEXTRACT_ANALYZE_ID_ENABLED:
        raise TextractUnavailable("TEXTRACT_ANALYZE_ID_ENABLED is False")

    try:
        client = _textract_client()
        response = client.analyze_id(DocumentPages=[{"Bytes": image_bytes}])
    except ImportError as e:
        raise TextractUnavailable(f"boto3 not installed: {e}") from e
    except Exception as e:
        raise TextractUnavailable(f"Textract AnalyzeID call failed: {e}") from e

    fields: Dict[str, str] = {}
    documents = response.get("IdentityDocuments", [])
    if not documents:
        return fields

    for id_field in documents[0].get("IdentityDocumentFields", []):
        field_type = (id_field.get("Type") or {}).get("Text")
        value = (id_field.get("ValueDetection") or {}).get("Text")
        if field_type and value:
            fields[field_type] = value

    return fields


# Textract AnalyzeID field-type -> PassportData field-name mapping (see
# specialized_ocr/passport_extractor.py:PassportData). Only the subset of
# AWS's documented IdentityDocumentFields.Type enum relevant to passports
# is mapped -- AnalyzeID does not return nationality or sex as separate
# fields for passports, which is why those two are derived from the MRZ
# line instead (see parse_mrz_line2 / map_to_passport_fields below).
_PASSPORT_FIELD_MAP = {
    "DOCUMENT_NUMBER": "passport_number",
    "LAST_NAME": "surname",
    "FIRST_NAME": "given_names",
    "DATE_OF_BIRTH": "date_of_birth",
    "DATE_OF_ISSUE": "date_of_issue",
    "EXPIRATION_DATE": "date_of_expiry",
    "MRZ_CODE": "mrz_line1",  # Textract returns both MRZ rows as one newline-joined field; re-split below
    "ADDRESS": "address",
}


def _century_for(two_digit_year: int, *, prefer_future: bool) -> int:
    """
    ICAO 9303 MRZ dates carry only a 2-digit year, so the century has to be
    inferred by convention: passport EXPIRY is conventionally in the future
    (prefer_future=True), DATE OF BIRTH is conventionally in the past
    (prefer_future=False). Pivoting on the current year is the standard
    approach every MRZ parser uses for this ambiguity.
    """
    current_year = datetime.now().year
    current_century = (current_year // 100) * 100
    candidate = current_century + two_digit_year
    if prefer_future:
        if candidate < current_year:
            candidate += 100
    else:
        if candidate > current_year:
            candidate -= 100
    return candidate


def _mrz_date_to_ddmmyyyy(yymmdd: str, *, prefer_future: bool) -> Optional[str]:
    """Convert an MRZ YYMMDD block to DD/MM/YYYY, or None if not parseable."""
    if not yymmdd or len(yymmdd) != 6 or not yymmdd.isdigit():
        return None
    yy, mm, dd = int(yymmdd[0:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return None
    year = _century_for(yy, prefer_future=prefer_future)
    return f"{dd:02d}/{mm:02d}/{year:04d}"


_MRZ_SEX_MAP = {"M": "Male", "F": "Female"}


def parse_mrz_line2(line2: str) -> Dict[str, str]:
    """
    Parse a TD3-format passport MRZ line 2 (the standard 44-character
    machine-readable line under the bio-data page) into nationality, sex,
    and the two dates it carries. This is the same fixed-position ICAO 9303
    layout the codebase's own regex fallback in passport_extractor.py
    already captures the raw line for (JSONExtractor._regex_extraction's
    "mrz_line2" pattern) -- this function is what actually decodes it,
    which nothing in this codebase did before now.

    TD3 line 2 layout (0-indexed, 44 chars):
      0-8   passport number (9, '<'-padded)      9   check digit
      10-12 nationality (3-letter code)
      13-18 date of birth YYMMDD                 19  check digit
      20    sex (M/F/<)
      21-26 expiry date YYMMDD                   27  check digit
      28-41 personal number (optional)           42  check digit
      43    overall check digit

    Returns whatever subset of {nationality, sex, date_of_birth,
    date_of_expiry} could be parsed -- never raises on malformed input,
    since MRZ OCR is exactly the kind of text that arrives slightly wrong.
    """
    result: Dict[str, str] = {}
    if not line2:
        return result

    cleaned = re.sub(r"\s+", "", line2.upper())
    if len(cleaned) < 28:
        return result

    nationality = cleaned[10:13].replace("<", "").strip()
    if nationality.isalpha() and len(nationality) == 3:
        result["nationality"] = nationality

    dob = _mrz_date_to_ddmmyyyy(cleaned[13:19], prefer_future=False)
    if dob:
        result["date_of_birth"] = dob

    sex_char = cleaned[20:21]
    if sex_char in _MRZ_SEX_MAP:
        result["sex"] = _MRZ_SEX_MAP[sex_char]

    expiry = _mrz_date_to_ddmmyyyy(cleaned[21:27], prefer_future=True)
    if expiry:
        result["date_of_expiry"] = expiry

    return result


def map_to_passport_fields(textract_fields: Dict[str, str]) -> Dict[str, str]:
    """
    Translate raw Textract AnalyzeID field names into PassportData's
    schema, filling nationality/sex/DOB/expiry from the MRZ line when
    Textract's own dedicated fields are missing or the MRZ disagrees with
    a garbled dedicated field (the MRZ checksum-bearing fields are
    generally the more reliable source for these four).
    """
    mapped: Dict[str, str] = {}
    for textract_key, our_key in _PASSPORT_FIELD_MAP.items():
        value = textract_fields.get(textract_key)
        if value:
            mapped[our_key] = value

    mrz_raw = textract_fields.get("MRZ_CODE", "")
    lines = [l.strip() for l in mrz_raw.splitlines() if l.strip()]
    if len(lines) >= 2:
        mapped["mrz_line1"] = lines[0]
        mapped["mrz_line2"] = lines[1]
        mapped.update(parse_mrz_line2(lines[1]))
    elif len(lines) == 1:
        # Single-line MRZ_CODE with no newline is occasionally what comes
        # back for a poorly-segmented image; nothing reliable to parse.
        mapped.setdefault("mrz_line1", lines[0])

    id_type = textract_fields.get("ID_TYPE", "")
    if id_type:
        mapped["document_type"] = id_type

    return mapped


MANDATORY_PASSPORT_FIELDS = (
    "passport_number", "surname", "given_names", "nationality",
    "date_of_birth", "sex", "date_of_expiry",
)


def is_passport_result_sufficient(mapped_fields: Dict[str, str]) -> bool:
    """
    True only when every PassportData mandatory field was filled (either
    by a direct Textract field or by MRZ parsing above). False is the
    expected outcome whenever the MRZ wasn't legible or Textract couldn't
    read the document at all -- callers should fall back to the
    vision-LLM path in that case, not treat it as an error.
    """
    return all(mapped_fields.get(f) for f in MANDATORY_PASSPORT_FIELDS)
