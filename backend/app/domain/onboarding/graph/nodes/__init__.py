"""Node implementations, grouped by the part of the flow they belong to.

    documents.py       Stage 5  — classify_account, collect_* document nodes
    members.py         Stage 7  — corporate-shareholder detection, member expansion
    key_individuals.py Stage 7  — the five KI-loop interrupt nodes
    compliance.py       Stage 8 — FATCA, PEP, product package, self-declaration
    completion.py       Stage 8 — the terminal node
"""

from __future__ import annotations
