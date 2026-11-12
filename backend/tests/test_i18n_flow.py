"""
i18n regression tests — docs/multilingual-flow-approach.html.

Run:  cd backend && python -m pytest tests/test_i18n_flow.py -q
(needs the app's env loaded, e.g. `set -a; . ../.env.docker; set +a` and
FRONTEND_LOG_DIR pointing somewhere writable).

Covers the language plumbing and the catalog without touching Supabase or
Bedrock: repositories are monkeypatched.
"""
import re

import pytest
from fastapi.testclient import TestClient

import app.main as main_mod
from app.i18n import LocalizedStr, render_message, localized, members_summary, i18n_metadata
from app.i18n.messages import MESSAGES, DOC_NAMES
from app.utils.language import request_language, normalize_language

app = main_mod.app


@app.get("/__test__/lang")
async def _echo_lang():
    return {"lang": request_language(), "explicit_none": normalize_language(None),
            "explicit_es": normalize_language("spanish")}


client = TestClient(app)


# ── Rule 3: language travels with every request ─────────────────────────────
@pytest.mark.parametrize("header,expected", [
    ("arabic", "arabic"), ("spanish", "spanish"), ("english", "english"),
    ("ar", "arabic"), ("es", "spanish"), ("klingon", "english"), (None, "english"),
])
def test_header_resolves_request_language(header, expected):
    headers = {"X-User-Language": header} if header else {}
    r = client.get("/__test__/lang", headers=headers)
    assert r.status_code == 200
    assert r.json()["lang"] == expected
    assert r.json()["explicit_none"] == expected
    # an explicit value still wins over the header
    assert r.json()["explicit_es"] == "spanish"


def test_language_does_not_leak_between_requests():
    assert client.get("/__test__/lang", headers={"X-User-Language": "arabic"}).json()["lang"] == "arabic"
    assert client.get("/__test__/lang").json()["lang"] == "english"


def test_cors_preflight_allows_language_header():
    r = client.options("/__test__/lang", headers={
        "Origin": "http://localhost:9000",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-user-language,content-type",
    })
    allowed = r.headers.get("access-control-allow-headers", "").lower()
    assert "x-user-language" in allowed, allowed


# ── Rule 2: catalog completeness ────────────────────────────────────────────
def test_catalog_has_all_languages_and_matching_placeholders():
    for key, tpl in MESSAGES.items():
        assert set(tpl) >= {"english", "arabic", "spanish"}, key
        ph = [set(re.findall(r"\{(\w+)\}", tpl[l])) for l in ("english", "arabic", "spanish")]
        assert ph[0] == ph[1] == ph[2], key


def test_arabic_catalog_is_actually_arabic():
    for key, tpl in MESSAGES.items():
        if key in ("ki.share_line",) or not re.search(r"[A-Za-z]{4}", tpl["english"]):
            continue
        assert re.search(r"[؀-ۿ]", tpl["arabic"]), key


def test_localized_str_is_a_plain_str_and_carries_all_variants():
    m = render_message("as_saved.upload_ids", "arabic", count=2, names="  1. A\n  2. B")
    assert isinstance(m, str) and isinstance(m, LocalizedStr)
    assert "الهوية الإماراتية" in m
    md = i18n_metadata(m)
    assert set(md["i18n"]) == {"english", "arabic", "spanish"}
    assert md["message_key"] == "as_saved.upload_ids"
    # data (names) is identical in every rendering
    for text in md["i18n"].values():
        assert "  1. A\n  2. B" in text
    # concatenation degrades to plain str (still valid)
    assert type("x" + m) is str


def test_as_saved_no_longer_asks_about_external_key_individuals():
    for key in ("as_saved.upload_ids", "as_saved.partially_verified", "as_saved.all_verified"):
        en = MESSAGES[key]["english"].lower()
        assert "anyone else" not in en and "outside this list" not in en and "?" not in en, key


def test_members_summary_translates_labels_not_names():
    rows = [{"name": "JAMES EDWARD WHITMORE", "is_as": True, "is_ubo": True, "share": "48", "verified": True}]
    s = members_summary(rows, "summary.header_registered", "spanish")
    assert "JAMES EDWARD WHITMORE" in s and "Firmante Autorizado" in s and "Personas registradas" in s
    assert "JAMES EDWARD WHITMORE" in s.in_language("arabic") and "مفوّض بالتوقيع" in s.in_language("arabic")


def test_bulk_success_message_localized():
    from app.services.bulk_upload_service import build_bulk_success_message
    m = build_bulk_success_message("ejari", {}, member_name=None,
                                   remaining_docs=["Memorandum of Association (MOA)"], language="arabic")
    assert "إيجاري" in m and "عقد التأسيس" in m
    assert "Ejari" in m.in_language("english")


# ── Storage + history: toggle serves stored rendering, no LLM ──────────────
def test_insert_conversation_log_persists_variants(monkeypatch):
    from app.services import chatupload_helpers as h
    captured = {}

    class _Res:
        data = [{"id": 1}]

    monkeypatch.setattr(h.ConversationRepository, "insert", staticmethod(lambda d: captured.update(d) or _Res()))
    msg = render_message("ki_loop.pep", "spanish", summary="")
    assert h.insert_conversation_log("a@b.c", "agent", msg, "chat", {"message_type": "ki_loop_finalized"})
    assert captured["message"] == str(msg) and type(captured["message"]) is str
    md = captured["metadata"]
    assert md["message_type"] == "ki_loop_finalized"
    assert md["i18n"]["arabic"].startswith("تم حفظ إقرار فاتكا")
    assert md["message_key"] == "ki_loop.pep"


def test_conversation_logs_serves_stored_variant_without_llm(monkeypatch):
    from app.api.routes.onboarding import conversation as conv
    rows = [{
        "id": 7, "role": "agent", "message": "FATCA declaration saved.",
        "metadata": {"language": "english", "message_type": "ki_loop_finalized",
                     "i18n": {"english": "FATCA declaration saved.", "arabic": "تم حفظ إقرار فاتكا.",
                              "spanish": "Declaración FATCA guardada."}},
    }]

    class _Res:
        data = rows

    monkeypatch.setattr(conv.ConversationRepository, "list_for_channel",
                        staticmethod(lambda *a, **k: _Res()))

    def _no_llm(*a, **k):
        raise AssertionError("LLM translation must not run for catalog rows")

    monkeypatch.setattr(conv, "translate_stored_messages_batch", _no_llm)
    for lang, expected in (("arabic", "تم حفظ إقرار فاتكا."), ("spanish", "Declaración FATCA guardada."),
                           ("english", "FATCA declaration saved.")):
        for r in rows:
            r["message"] = "FATCA declaration saved."
        r = client.get("/onboarding/ai/api/chatupload/conversation-logs/a@b.c",
                       params={"language": lang, "limit": 10})
        assert r.status_code == 200, r.text
        assert r.json()["logs"][0]["message"] == expected
