"""
app/services/image_redaction_service.py
========================================
Pixel-level PII redaction for document IMAGES (not text).

WHEN TO USE THIS
-----------------
Only for a path where a document image copy has to leave the core KYC
pipeline for a reason unrelated to reading its fields — a support ticket,
an external audit export, a lower-trust admin view, or any future
vision-LLM call that doesn't need to read the PII fields it's looking at.

DO NOT put this in front of the primary EID/Passport extraction call
(`call_vision_llm()` in llm_client.py). Redacting the name/ID number/DOB
on an EID or passport image and THEN sending it to a vision model defeats
the point — those fields are exactly what that call exists to read. The
fix there is to stop sending the image to a third-party LLM at all: call
Textract `AnalyzeID` instead (structured fields, no image transmitted
outside AWS). See backend/docs/architecture/pii-masking-guardrails.md §7.2.

This module is the tool for the OTHER case: "I have an image and I need a
sanitized copy of it, full stop" — which is what the AWS-native pattern
(Textract for text bounding boxes + Rekognition for faces + Pillow to draw
over them) is actually for.

Design notes
------------
- Textract `AnalyzeID` does NOT return Geometry/BoundingBox on its fields
  (its IdentityDocumentFields response is text-only), so it can't drive
  pixel redaction by itself. This module uses `detect_document_text`
  instead (plain OCR), which DOES return a Geometry.BoundingBox per LINE,
  and flags lines whose text matches a known PII shape.
- Detection here is deliberately permissive: a false positive costs one
  extra black box, a false negative leaks a field. Bias toward redacting.
- Region: pass the same region you land on for Bedrock/Textract per
  pii-masking-guardrails.md §9 (confirm Textract/Rekognition availability
  there before committing to it for identity documents).
- Not wired into any caller yet — this is a standalone module ready to be
  imported wherever a redacted derivative is actually needed.
"""

import io
import os
import re
import logging
from dataclasses import dataclass

import boto3
from PIL import Image, ImageDraw, ImageFilter

logger = logging.getLogger(__name__)

AWS_REGION = os.environ.get("PII_REDACTION_AWS_REGION", os.environ.get("AWS_REGION", "me-central-1"))

_textract = None
_rekognition = None


def _textract_client():
    global _textract
    if _textract is None:
        _textract = boto3.client("textract", region_name=AWS_REGION)
    return _textract


def _rekognition_client():
    global _rekognition
    if _rekognition is None:
        _rekognition = boto3.client("rekognition", region_name=AWS_REGION)
    return _rekognition


# UAE-specific shapes from pii-masking-guardrails.md §4.2 — illustrative;
# verify against real (anonymized) extracted samples before trusting these
# in production, especially before ever using BLOCK-style behavior on them.
PII_PATTERNS = [
    re.compile(r"\b784-\d{4}-\d{7}-\d\b"),             # UAE Emirates ID
    re.compile(r"^[A-Z0-9<]{20,44}$"),                  # MRZ-shaped line
    re.compile(r"\b[A-Z]{1,2}\d{6,9}\b"),               # generic passport-no. shape
    re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"),    # IBAN
    re.compile(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b"),         # DD/MM/YYYY dates (DOB, expiry)
]


@dataclass
class RedactionBox:
    left: int
    top: int
    right: int
    bottom: int
    reason: str


def _normalized_to_pixels(bbox: dict, width: int, height: int) -> tuple[int, int, int, int]:
    left = int(bbox["Left"] * width)
    top = int(bbox["Top"] * height)
    right = int((bbox["Left"] + bbox["Width"]) * width)
    bottom = int((bbox["Top"] + bbox["Height"]) * height)
    return left, top, right, bottom


def find_text_pii_boxes(image_bytes: bytes, width: int, height: int) -> list[RedactionBox]:
    """OCR the image and return a box for every LINE that matches a PII shape."""
    resp = _textract_client().detect_document_text(Document={"Bytes": image_bytes})
    boxes: list[RedactionBox] = []
    for block in resp.get("Blocks", []):
        if block.get("BlockType") != "LINE":
            continue
        text = block.get("Text", "")
        if any(p.search(text) for p in PII_PATTERNS):
            left, top, right, bottom = _normalized_to_pixels(
                block["Geometry"]["BoundingBox"], width, height
            )
            boxes.append(RedactionBox(left, top, right, bottom, reason=f"pii_pattern:{text[:4]}…"))
    return boxes


def find_face_boxes(image_bytes: bytes, width: int, height: int) -> list[RedactionBox]:
    """Locate faces (the ID photo) via Rekognition so they get boxed out too."""
    resp = _rekognition_client().detect_faces(Image={"Bytes": image_bytes})
    boxes: list[RedactionBox] = []
    for face in resp.get("FaceDetails", []):
        left, top, right, bottom = _normalized_to_pixels(face["BoundingBox"], width, height)
        boxes.append(RedactionBox(left, top, right, bottom, reason="face"))
    return boxes


def redact_image(image_bytes: bytes, boxes: list[RedactionBox], method: str = "blackout") -> bytes:
    """Draw over the given boxes on a COPY of the image. Original bytes are untouched."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(img)

    for box in boxes:
        if method == "blackout":
            draw.rectangle([box.left, box.top, box.right, box.bottom], fill="black")
        elif method == "blur":
            region = img.crop((box.left, box.top, box.right, box.bottom))
            region = region.filter(ImageFilter.GaussianBlur(radius=18))
            img.paste(region, (box.left, box.top))
        else:
            raise ValueError(f"unknown redaction method: {method!r}")

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def build_redacted_derivative(image_bytes: bytes, method: str = "blackout") -> bytes:
    """
    Entry point. Raw document image bytes in, redacted PNG bytes out.
    The caller decides what to do with the result (attach to a ticket, hand
    to an admin view, or — only if the use case genuinely doesn't need the
    real fields — pass to a vision LLM).
    """
    img = Image.open(io.BytesIO(image_bytes))
    width, height = img.size

    boxes = find_text_pii_boxes(image_bytes, width, height) + find_face_boxes(image_bytes, width, height)
    if not boxes:
        logger.warning(
            "build_redacted_derivative: no PII/face regions detected on a %dx%d image — "
            "verify this isn't a false negative before trusting the output as sanitized",
            width, height,
        )

    return redact_image(image_bytes, boxes, method=method)
