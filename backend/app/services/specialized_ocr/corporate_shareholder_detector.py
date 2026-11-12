# specialized_ocr/corporate_shareholder_detector.py
"""
Type-2 Multiple Owner Corporate Shareholder Detection
======================================================
After a Commercial License is extracted for a Partnership/Multiple Owner account,
this module scans the partners list to detect corporate entities (LLC, LTD, etc.)
and triggers the Certificate of Incorporation (CoI) collection flow.

It also handles ownership expansion once CoI documents are available:
    corporate_share_pct × individual_raw_pct / 100 → individual_effective_pct

UBO threshold: anyone with effective ownership > 25% is a UBO.
"""

import re
from typing import List, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# CORPORATE ENTITY DETECTION PATTERNS
# ============================================================================

CORPORATE_SUFFIXES = [
    # English
    "llc", "l.l.c", "l.l.c.",
    "ltd", "limited",
    "inc", "incorporated",
    "corp", "corporation",
    "holding", "holdings",
    "group",
    "plc", "p.l.c",
    "s.a", "sa",
    "bv", "b.v",
    "gmbh",
    "fze", "fzco", "fzc",          # UAE Free Zone
    "pjsc", "p.j.s.c",             # UAE Public Joint Stock
    "psc",
    "co.", "co,",
    "company",
    "enterprises",
    "international",
    "ventures",
    "capital",
    "investments",
    "fund",
    "trust",
]

# Regex built at module load time for performance
_SUFFIX_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in CORPORATE_SUFFIXES) + r")\b",
    re.IGNORECASE,
)

# Arabic personal name particles — if any are present and no corporate suffix,
# the name is very likely a natural person even when written all-caps on UAE docs.
# Examples: SAEED HAMDAN AL MAZROUEI, MOHAMMED BIN RASHID AL MAKTOUM
_ARABIC_PARTICLE_PATTERN = re.compile(
    r"\b(AL|BIN|BINT|ABU|UMM|IBN|BANU|AL-|BIN-|BINTE|UMMU)\b",
    re.IGNORECASE,
)


def is_corporate_entity(name: str) -> bool:
    """
    Return True if the given name looks like a corporate entity
    rather than a natural person.

    Heuristics used (any match → corporate):
    1. Contains a recognised corporate suffix (LLC, LTD, Group, etc.)
    2. Name is ALL UPPERCASE and longer than 20 chars (typical for entity names on licences)
    3. Contains digits followed by letters (e.g. "123 Holdings")
    """
    if not name or len(name.strip()) < 3:
        return False

    name_stripped = name.strip()

    # Heuristic 1: corporate suffix
    if _SUFFIX_PATTERN.search(name_stripped):
        return True

    # Heuristic 2 (DISABLED): all-caps long name heuristic caused too many false positives
    # on foreign personal names (Turkish, Indian, etc.) that are written in ALL-CAPS on
    # UAE commercial licences but are clearly natural persons.
    # Example false positive: "ABDULLAH SATILMIS MAVIS" (Turkish, 23 chars, all-caps, no suffix)
    # Relying solely on Heuristic 1 (corporate suffix) is safer and more accurate.
    # If a genuine corporate entity is missed, it will always have a suffix like LLC/LTD/GROUP.

    return False


def _to_float_pct(value) -> float:
    """
    Normalise an OCR-extracted share-percentage value to a float. Handles
    plain numbers, numeric strings, and strings with a trailing "%" (e.g.
    "60%", "60 %") — OCR output isn't consistent about including the sign.
    Falls back to 0.0 for anything unparseable rather than raising, since a
    single malformed field shouldn't crash the whole ownership expansion.
    """
    try:
        return float(str(value).replace("%", "").strip())
    except (ValueError, TypeError):
        return 0.0


# ============================================================================
# PARTNER LIST SCANNER
# ============================================================================

def detect_corporate_shareholders(partners: List[Dict]) -> Dict:
    """
    Scan a partners list (from TradeLicenseExtractor output) and classify
    each partner as individual or corporate.

    Args:
        partners: list of partner dicts from Commercial License extraction.
                  Each dict is expected to have at least:
                  {
                      "name_english": str,
                      "share_percentage": float | str,
                      ...
                  }

    Returns:
        {
            "has_corporate_shareholders": bool,
            "individual_partners": [ {name, share_percentage, ...} ],
            "corporate_shareholders": [
                {
                    "name": str,
                    "share_percentage": float,
                    "coi_collected": False,
                    "coi_output_path": None,
                    "expanded_individuals": []
                },
                ...
            ]
        }
    """
    individual_partners = []
    corporate_shareholders = []

    for partner in partners:
        name = (partner.get("name_english") or "").strip()
        share = _to_float_pct(partner.get("share_percentage", 0))

        if is_corporate_entity(name):
            logger.info(f"[CORPORATE DETECTED] '{name}' ({share}%) flagged as corporate entity")
            corporate_shareholders.append({
                "name": name,
                "share_percentage": share,
                "coi_collected": False,
                "coi_output_path": None,
                "expanded_individuals": [],
            })
        else:
            individual_partners.append({**partner, "share_percentage": share})

    result = {
        "has_corporate_shareholders": len(corporate_shareholders) > 0,
        "individual_partners": individual_partners,
        "corporate_shareholders": corporate_shareholders,
    }

    logger.info(
        f"[CORPORATE DETECTOR] Found {len(corporate_shareholders)} corporate "
        f"and {len(individual_partners)} individual partner(s)."
    )
    return result


# ============================================================================
# OWNERSHIP EXPANSION
# ============================================================================

def expand_ownership(
    individual_partners: List[Dict],
    corporate_shareholders: List[Dict],
) -> List[Dict]:
    """
    Expand corporate shareholders into their individual beneficial owners
    and compute effective ownership percentages.

    Algorithm:
        effective_pct = corporate_share_pct × individual_raw_pct / 100

    Args:
        individual_partners:   partners already confirmed as natural persons.
        corporate_shareholders: corporate partners, each must have
                                "expanded_individuals" populated from CoI extraction,
                                e.g. [{"name": "John Smith", "share_percentage": 70}, ...]

    Returns:
        List of expanded owners:
        [
            {
                "name": str,
                "effective_percentage": float,
                "source": "direct" | "corporate_expansion",
                "corporate_parent": str | None,
                "raw_percentage": float,     # original pct in corporate (for expansion entries)
                "is_ubo": bool,
            },
            ...
        ]
    """
    expanded: List[Dict] = []

    # 1. Direct individual partners keep their share as-is
    for p in individual_partners:
        name = (p.get("name_english") or p.get("name") or "").strip()
        share = _to_float_pct(p.get("share_percentage", 0))
        expanded.append({
            "name": name,
            "effective_percentage": round(share, 4),
            "source": "direct",
            "corporate_parent": None,
            "raw_percentage": share,
            "is_ubo": False,  # filled by compute_ubo()
        })

    # 2. Expand corporate shareholders
    for corp in corporate_shareholders:
        corp_name = corp.get("name", "")
        corp_share = _to_float_pct(corp.get("share_percentage", 0))
        individuals = corp.get("expanded_individuals", [])

        if not individuals:
            # CoI not yet collected — add a placeholder so the caller knows
            logger.warning(
                f"[EXPAND]  No individuals found for corporate '{corp_name}'. "
                f"CoI may not yet be collected."
            )
            continue

        for ind in individuals:
            ind_name = (ind.get("name_english") or ind.get("name") or "").strip()
            # CoI-extracted share_percentage comes straight from OCR and, unlike
            # the Commercial License partners list (parsed defensively in
            # detect_corporate_shareholders), was never normalised — a raw
            # "60%" string here used to blow up float() and get silently
            # swallowed by the caller's try/except, which looked identical to
            # "CoI not ready yet" and fell back to the manual "type Okay" path.
            ind_raw_pct = _to_float_pct(ind.get("share_percentage", 0))
            effective = round(corp_share * ind_raw_pct / 100.0, 4)

            expanded.append({
                "name": ind_name,
                "effective_percentage": effective,
                "source": "corporate_expansion",
                "corporate_parent": corp_name,
                "raw_percentage": ind_raw_pct,
                "is_ubo": False,  # filled by compute_ubo()
            })
            logger.info(
                f"[EXPAND] {ind_name}: {corp_share}% × {ind_raw_pct}% / 100 = {effective}%"
            )

    return expanded


# ============================================================================
# UBO COMPUTATION
# ============================================================================

UBO_THRESHOLD = 25.0  # Anyone with effective ownership > 25% is flagged as UBO


def compute_ubo(expanded_owners: List[Dict]) -> List[Dict]:
    """
    Tag each expanded owner as UBO or not based on effective_percentage > UBO_THRESHOLD.
    Mutates the list in-place and returns it for convenience.

    Args:
        expanded_owners: output from expand_ownership()

    Returns:
        Same list with "is_ubo" field set.
    """
    for owner in expanded_owners:
        owner["is_ubo"] = owner["effective_percentage"] > UBO_THRESHOLD

    ubo_names = [o["name"] for o in expanded_owners if o["is_ubo"]]
    logger.info(
        f"[UBO] Threshold: >{UBO_THRESHOLD}%  |  "
        f"UBO(s) identified: {ubo_names if ubo_names else 'None'}"
    )

    return expanded_owners


# ============================================================================
# CONVENIENCE: FULL PIPELINE (detect → expand → UBO)
# ============================================================================

def run_type2_analysis(
    partners: List[Dict],
    coi_map: Optional[Dict[str, List[Dict]]] = None,
) -> Dict:
    """
    Full Type-2 analysis pipeline:
    1. Detect corporate shareholders in the partners list
    2. If coi_map is provided, populate expanded_individuals for each corporate entity
    3. Run expand_ownership()
    4. Run compute_ubo()

    Args:
        partners:  raw partners list from Commercial License extraction
        coi_map:   dict mapping corporate_name → list of individuals from CoI
                   e.g. {"ALPINE CAPITAL GROUP LIMITED": [{"name": "John Smith", "share_percentage": 70}, ...]}
                   Pass None if CoI collection is not yet complete.

    Returns:
        {
            "detection": detect_corporate_shareholders() result,
            "expanded_owners": list | None,   (None if CoI not yet complete)
            "ubo_names": [str, ...] | [],
            "coi_required": bool,
            "pending_coi": [str, ...],         list of corporate names still needing CoI
        }
    """
    detection = detect_corporate_shareholders(partners)

    # If no corporate shareholders, nothing more to do
    if not detection["has_corporate_shareholders"]:
        return {
            "detection": detection,
            "expanded_owners": None,
            "ubo_names": [],
            "coi_required": False,
            "pending_coi": [],
        }

    # Populate CoI data if available
    if coi_map:
        for corp in detection["corporate_shareholders"]:
            corp_name = corp["name"]
            # Try exact match first, then case-insensitive
            if corp_name in coi_map:
                corp["expanded_individuals"] = coi_map[corp_name]
                corp["coi_collected"] = True
            else:
                for key, individuals in coi_map.items():
                    if key.strip().lower() == corp_name.strip().lower():
                        corp["expanded_individuals"] = individuals
                        corp["coi_collected"] = True
                        break

    # Check which corporate entities still need CoI
    pending_coi = [
        corp["name"]
        for corp in detection["corporate_shareholders"]
        if not corp["coi_collected"]
    ]

    if pending_coi:
        return {
            "detection": detection,
            "expanded_owners": None,
            "ubo_names": [],
            "coi_required": True,
            "pending_coi": pending_coi,
        }

    # All CoI collected — run expansion and UBO
    expanded = expand_ownership(
        detection["individual_partners"],
        detection["corporate_shareholders"],
    )
    expanded = compute_ubo(expanded)

    ubo_names = [o["name"] for o in expanded if o["is_ubo"]]

    return {
        "detection": detection,
        "expanded_owners": expanded,
        "ubo_names": ubo_names,
        "coi_required": False,
        "pending_coi": [],
    }
