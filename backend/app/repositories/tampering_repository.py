# backend/app/repositories/tampering_repository.py
"""
Queries against the three document-forensics tables.

    tampering_test_reports    one row per document analysed — the verdict
    tampering_module_results  one row per detection module that ran
    tampering_llm_analysis    the model's written explanation of the verdict

Two callers, two column sets
----------------------------
`documentpage` (rendering the tamper badge in the UI) and `document_messaging`
(composing the email a customer receives) read the same tables with
**different column lists** — the UI needs a handful of fields, the email path
takes `select("*")`. Both are preserved as separate methods rather than
collapsed onto `"*"`: these rows carry full forensic evidence blobs, and
widening the UI query would pull them into every document-status render.

The `client` parameter
----------------------
`document_messaging` obtains its client from `get_supabase_client()` and passes
it in, while `documentpage` uses the module-level anon client. Rather than pick
one, every method takes an optional `client` and defaults to the anon client —
the same resolution used by `UserRepository`.
"""

from __future__ import annotations

import logging
from typing import Any

from app.repositories.base import supabase

logger = logging.getLogger(__name__)

TEST_REPORTS = "tampering_test_reports"
MODULE_RESULTS = "tampering_module_results"
LLM_ANALYSIS = "tampering_llm_analysis"

# The narrow set the document-status UI renders. Deliberately excludes the
# evidence blobs.
COLUMNS_REPORT_SUMMARY = "id, decision, status, overall_score, case_id, created_at"
COLUMNS_MODULE_SUMMARY = "module_name, status, score, evidence"
COLUMNS_LLM_SUMMARY = "analysis_text, tampered_sections, recommendations"


def _client(client: Any = None) -> Any:
    """Resolve the client to use. Defaults to the anon client."""
    return client if client is not None else supabase


class TamperingRepository:
    """Query methods for the tampering tables. Stateless; all methods static."""

    # ------------------------------------------------------------------
    # tampering_test_reports
    # ------------------------------------------------------------------

    @staticmethod
    def latest_report_for_file(file_path: str, *, client: Any = None) -> Any:
        """
        The most recent verdict for one document, summary columns only.

        Ordered newest-first and limited to one because a document can be
        re-analysed after re-upload; only the latest verdict is shown.
        """
        return (
            _client(client)
            .table(TEST_REPORTS)
            .select(COLUMNS_REPORT_SUMMARY)
            .eq("file_path", file_path)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

    @staticmethod
    def get_report(test_report_id: Any, *, client: Any = None) -> Any:
        """
        Full report row by id — `select("*")`.

        Used when composing the customer email, which quotes the evidence.
        """
        return (
            _client(client)
            .table(TEST_REPORTS)
            .select("*")
            .eq("id", test_report_id)
            .execute()
        )

    # ------------------------------------------------------------------
    # tampering_module_results
    # ------------------------------------------------------------------

    @staticmethod
    def module_summaries(test_report_id: Any, *, client: Any = None) -> Any:
        """Per-module outcomes for one report, summary columns only (UI)."""
        return (
            _client(client)
            .table(MODULE_RESULTS)
            .select(COLUMNS_MODULE_SUMMARY)
            .eq("test_report_id", test_report_id)
            .execute()
        )

    @staticmethod
    def module_results(test_report_id: Any, *, client: Any = None) -> Any:
        """Per-module outcomes, full rows — `select("*")` (email composition)."""
        return (
            _client(client)
            .table(MODULE_RESULTS)
            .select("*")
            .eq("test_report_id", test_report_id)
            .execute()
        )

    # ------------------------------------------------------------------
    # tampering_llm_analysis
    # ------------------------------------------------------------------

    @staticmethod
    def latest_llm_analysis(test_report_id: Any, *, client: Any = None) -> Any:
        """
        The newest written analysis for a report.

        Ordered on `generated_at` — note this table orders by a different column
        than `tampering_test_reports` does (`created_at`). That is the schema as
        it stands, not a slip.
        """
        return (
            _client(client)
            .table(LLM_ANALYSIS)
            .select(COLUMNS_LLM_SUMMARY)
            .eq("test_report_id", test_report_id)
            .order("generated_at", desc=True)
            .limit(1)
            .execute()
        )
