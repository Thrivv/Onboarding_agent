"""
Pydantic-backed schema validation for specialized OCR extractor output.

prompt-remediation Phase 4: every bilingual extractor's JSON-repair path
(see e.g. EjariExtractor.extract_with_ai) already retries malformed JSON
with a regex trailing-comma fix, but once json.loads() succeeded the result
was trusted blindly from there -- the old `ensure_all_fields()` only filled
in missing KEYS with "", it never checked that a value was actually a
string, so a field the model returned as a bare int/float/bool/list/dict
would silently flow downstream into regex-based post-processing
(post_process_data, validate_field_lengths, ...) that assumes str and can
raise or silently mis-format on anything else.

`validate_and_coerce()` builds a permissive pydantic model on the fly from
the field-name list every extractor already has (ENGLISH_FIELDS,
ARABIC_FIELDS, SINGLE_OWNER_ENGLISH_FIELDS, ...), rather than requiring
20-34 field names to be hand-typed per extractor. It guarantees the exact
same output SHAPE the old ensure_all_fields() did -- a dict with every
field present, string-valued, missing/None -> "" -- so it is a drop-in
replacement at every existing call site, but the guarantee is now enforced
by a real schema instead of an unchecked dict comprehension. It never
raises: a field pydantic can't validate for an unexpected reason falls back
to the previous dict.get()-with-str() behaviour for that one field rather
than failing the whole extraction.

Scope: used for the flat, all-string field sets (Ejari, MOA, Trade License
single/multi-owner english+arabic). BVI and Passport already have their own
hand-rolled presence/shape validators (_validate / PassportValidator) and
were left alone -- BVI's directors_and_shareholders list mixes real types
(share_percentage as a number, is_agent-style booleans on Trade's
manager/partner rows) that a generic string-only schema would corrupt, so
extending this pattern there needs per-field typing this pass didn't do.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Sequence, Type

from pydantic import BaseModel, ValidationError, create_model, model_validator

logger = logging.getLogger(__name__)

_MODEL_CACHE: Dict[tuple, Type[BaseModel]] = {}


def _coerce_before(cls, data: Any) -> Any:
    """model_validator(mode='before'): stringify every value up front
    (None -> ''), so the per-field Optional[str] check can never reject the
    payload for the one thing ensure_all_fields() never checked in the
    first place -- a stray int/float/bool/list/dict from the model."""
    if not isinstance(data, dict):
        return data
    out = {}
    for k, v in data.items():
        if v is None:
            out[k] = ""
        elif isinstance(v, str):
            out[k] = v
        else:
            out[k] = str(v)
    return out


def _build_model(schema_name: str, fields: Sequence[str]) -> Type[BaseModel]:
    cache_key = (schema_name, tuple(fields))
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached
    field_defs = {f: (Optional[str], "") for f in fields}
    model_cls = create_model(
        schema_name,
        __validators__={"_coerce_before": model_validator(mode="before")(classmethod(_coerce_before))},
        **field_defs,
    )
    _MODEL_CACHE[cache_key] = model_cls
    return model_cls


def validate_and_coerce(data: Dict[str, Any], fields: Sequence[str], schema_name: str) -> Dict[str, str]:
    """Drop-in replacement for the old `ensure_all_fields(data, fields)`:
    identical input/output shape (dict, every field present, string-valued,
    missing -> ""), now backed by a real pydantic schema instead of a bare
    dict comprehension. Never raises -- any validation failure falls back
    to the old plain-dict behaviour so extraction still completes."""
    if not isinstance(data, dict):
        data = {}
    try:
        model_cls = _build_model(schema_name, fields)
        instance = model_cls(**{f: data.get(f) for f in fields})
        result = instance.model_dump()
        return {f: (result.get(f) or "") for f in fields}
    except ValidationError as e:
        logger.warning(f"{schema_name} schema validation failed, falling back to raw field-fill: {e}")
        return {f: ("" if data.get(f) is None else str(data.get(f))) for f in fields}
    except Exception as e:
        logger.warning(f"{schema_name} schema validation errored unexpectedly ({e}), falling back to raw field-fill")
        return {f: ("" if data.get(f) is None else str(data.get(f))) for f in fields}
