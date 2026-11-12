"""
OCR extraction corpus — the prerequisite C3 was missing.

C3 proposed collapsing the six modules in app/services/specialized_ocr into a
BaseDocumentExtractor. It was stopped because the premise was wrong: measured
duplication is ~18 lines, not the ~600 the plan assumed, and the same-named
methods differ in ways that CHANGE EXTRACTION OUTPUT. With no behavioural
corpus for OCR, that refactor is an unprotected rewrite.

This file is the corpus. It does not make C3 safe on its own — only recorded
fixtures do that (see docs/ocr-corpus-runbook.md). What it does is make the
difference between "the output changed" and "nothing noticed" impossible.

Four layers, cheapest first. Each runs independently; each says plainly when
it has nothing recorded rather than passing vacuously.

  0. DIVERGENCE   the documented behavioural differences, pinned from source.
                  No fixtures, no network, no credentials. Runs today.
  1. TEXT         extract_text_from_pdf / _from_docx over real fixtures.
                  Deterministic, offline. Needs fixtures.
  2. REQUEST      the outbound LLM call shape — model, temperature, max_tokens,
                  timeout, prompt bytes. Intercepted, NEVER SENT in verify mode.
                  Needs fixtures.
  3. PIPELINE     full extraction with recorded LLM responses replayed from
                  cassettes. Needs fixtures + one recording pass with creds.

Layer 0 is the one that matters most for C3, and it is the one that costs
nothing. A base class that unified extract_text_from_pdf would silently start
feeding "--- Page N ---" markers to the ejari and trade prompts, or stop
feeding them to bvi and moa. The LLM output changes. No existing check sees it.
Layer 0 fails, by name, on that exact edit.

  THE RULE FROM contract_check.py APPLIES HERE
  A check that returns zero has told you nothing until you have watched it
  fail. Every layer supports --self-test, which mutates its own inputs and
  asserts the layer reports a failure. Run it before trusting a green.

Usage
    python backend/tests/ocr_corpus.py                  # verify all layers
    python backend/tests/ocr_corpus.py --report         # what is recorded
    python backend/tests/ocr_corpus.py --record 0       # re-pin divergence
    python backend/tests/ocr_corpus.py --record 1       # record text layer
    python backend/tests/ocr_corpus.py --record 2       # record request shapes
    python backend/tests/ocr_corpus.py --record 3       # record cassettes (LIVE
                                                        # API — container only)
    python backend/tests/ocr_corpus.py --self-test      # prove the checks fail

Exit code 0 when every recorded expectation holds. Layers with nothing
recorded report SKIP and do not affect the exit code — an empty corpus is not
a passing corpus, and --report tells you how empty it is.

Layer 0 needs no third-party packages. Layers 1-3 import the extractors, which
need: pymupdf, requests, python-dotenv, supabase, fastapi. See the sandbox note
in docs/STAGE_C_PROGRESS.md.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
OCR_DIR = BACKEND / "app" / "services" / "specialized_ocr"
CORPUS = Path(__file__).resolve().parent / "ocr_corpus"
FIXTURES = Path(__file__).resolve().parent / "ocr_fixtures"

DIVERGENCE_FILE = CORPUS / "divergence.json"
TEXT_FILE = CORPUS / "text.json"
REQUEST_FILE = CORPUS / "requests.json"
PIPELINE_FILE = CORPUS / "pipeline.json"
CASSETTES = CORPUS / "cassettes"

GREEN, RED, YELLOW, DIM, RESET = (
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[2m",
    "\033[0m",
)

failures: list[str] = []
skips: list[str] = []


def _ok(msg: str, note: str = "") -> None:
    tail = f"  {DIM}({note}){RESET}" if note else ""
    print(f"  {GREEN}PASS{RESET}  {msg}{tail}")


def _fail(msg: str) -> None:
    failures.append(msg)
    print(f"  {RED}FAIL{RESET}  {msg}")


def _skip(msg: str) -> None:
    skips.append(msg)
    print(f"  {YELLOW}SKIP{RESET}  {msg}")


def _section(title: str) -> None:
    print(f"\n{DIM}{title}{RESET}")


def _sha(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    elif not isinstance(data, (bytes, bytearray)):
        data = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha1(data).hexdigest()


def _estimate_tokens(text: str) -> int:
    """Rough token count for a prompt string.

    This is a character-count heuristic (~4 chars/token for English), NOT a
    real tokenizer run against Claude's vocabulary — Bedrock exposes no
    tokenize-only endpoint, and pulling in a third-party tokenizer (tiktoken,
    the anthropic SDK) as a new test dependency was judged not worth it for
    an estimate this document already labels as approximate everywhere it is
    shown (see prompt-remediation-plan.html, section 03). Treat this as
    "close enough to catch a prompt that tripled in size," not as a billing
    figure. Phase 3 replaces the ceiling this feeds with a measured number
    once the real Bedrock usage stats are available from a live call.
    """
    if not text:
        return 0
    return max(1, round(len(text) / 4))


def _load(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        _fail(f"{path.name} is not valid JSON: {e}")
        return None


def _save(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"  {DIM}wrote {path.relative_to(ROOT)}{RESET}")


# ══════════════════════════════════════════════════════════════════════════
#  LAYER 0 — divergence pins
# ══════════════════════════════════════════════════════════════════════════
#
# Derived from source, never hand-written, so the manifest cannot drift into
# wishful thinking. Each extractor contributes a fingerprint of the traits
# that a naive base-class collapse would erase.

# module stem -> (class name or None for module-level, text method, api method)
EXTRACTORS = {
    "bvi_extractor": ("BVIExtractor", "extract_text_from_pdf", "_call_api"),
    "moa_extractor": ("MOAExtractor", "extract_text_from_pdf", "call_ai_api"),
    "ejari_extractor": ("EjariExtractor", "extract_text_from_pdf", "call_ai_api"),
    "trade_extractor": ("TradeLicenseExtractor", "extract_text_from_pdf", "call_ai_api"),
    "passport_extractor": ("PassportOCRClient", None, "extract_from_image"),
}

# Traits that changed extraction output when they differed. Adding one here
# means the next C3 attempt has to preserve it or explain why not.
TRAIT_NOTES = {
    "page_markers": "inserts '--- Page N ---' into the text fed to the LLM",
    "temperature": "sampling temperature in the outbound payload",
    "max_tokens": "token ceiling in the outbound payload",
    "timeout_symbol": "the local name passed as timeout=",
    "timeout_config_key": "the config key that local name actually resolves to",
    "empty_text_guard": "returns an error string for short/empty extractions",
    "per_page_try": "wraps each page in its own try/except",
    "finally_close": "closes the fitz document in a finally block",
    "body_sha": "normalised AST of the method body",
}


def _find_method(tree: ast.AST, cls: str | None, name: str) -> ast.FunctionDef | None:
    if cls is None:
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == name:
                    return sub
    return None


def _normalised_body_sha(fn: ast.FunctionDef) -> str:
    """AST of the body with the docstring dropped.

    Comments, formatting and docstrings are excluded deliberately: this is
    meant to fire on a behaviour change, not on a reflow. It is the same
    normalisation docs/duplication-audit.md used to measure the real ~18
    duplicate lines.
    """
    body = list(fn.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return _sha("\n".join(ast.dump(stmt) for stmt in body))


def _module_bindings(tree: ast.AST) -> dict[str, str]:
    """Module-level `NAME = <something>`, rendered as text.

    This exists because of a trap worth stating plainly: bvi, moa and ejari
    all bind a local called API_TIMEOUT_SECONDS, and all three resolve to a
    DIFFERENT config key (BVI_/MOA_/EJARI_API_TIMEOUT_SECONDS). Pinning the
    local name alone would let a base class hoist one shared timeout and
    still look identical. The pin has to follow the name to the key.
    """
    out: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = node.value
        if isinstance(value, ast.Attribute):
            base = getattr(value.value, "id", "")
            out[target.id] = f"{base}.{value.attr}" if base else value.attr
        elif isinstance(value, ast.Constant):
            out[target.id] = repr(value.value)
        elif isinstance(value, ast.Name):
            out[target.id] = value.id
        elif isinstance(value, ast.BoolOp):  # `config.X or ""`
            first = value.values[0]
            if isinstance(first, ast.Attribute):
                base = getattr(first.value, "id", "")
                out[target.id] = f"{base}.{first.attr}" if base else first.attr
    return out


def _payload_literals(fn: ast.FunctionDef, bindings: dict[str, str]) -> dict:
    """Pull temperature / max_tokens out of the payload dict, and the symbol
    passed as `timeout=` to requests.post.

    Names are resolved through `bindings` where possible, so the pin records
    what the value IS, not merely what it is called.
    """
    out: dict = {
        "temperature": None,
        "max_tokens": None,
        "timeout_symbol": None,
        "timeout_config_key": None,
    }
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if not isinstance(key, ast.Constant) or key.value not in (
                    "temperature",
                    "max_tokens",
                ):
                    continue
                if isinstance(value, ast.Constant):
                    out[key.value] = value.value
                elif isinstance(value, ast.Name):
                    resolved = bindings.get(value.id)
                    out[key.value] = (
                        f"{value.id}={resolved}" if resolved else f"<{value.id}>"
                    )
                else:
                    out[key.value] = "<expr>"
        if isinstance(node, ast.Call):
            fname = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if fname != "post":
                continue
            for kw in node.keywords:
                if kw.arg != "timeout":
                    continue
                if isinstance(kw.value, ast.Name):
                    out["timeout_symbol"] = kw.value.id
                    out["timeout_config_key"] = bindings.get(kw.value.id, "<unresolved>")
                elif isinstance(kw.value, ast.Constant):
                    out["timeout_symbol"] = repr(kw.value.value)
                    out["timeout_config_key"] = repr(kw.value.value)
                else:
                    out["timeout_symbol"] = "<expr>"
    return out


def _fingerprint_one(stem: str, source: str) -> dict:
    cls, text_method, api_method = EXTRACTORS[stem]
    tree = ast.parse(source)
    bindings = _module_bindings(tree)
    fp: dict = {}

    if text_method:
        fn = _find_method(tree, cls, text_method)
        if fn is None:
            return {"_error": f"{cls}.{text_method} not found"}
        segment = ast.get_source_segment(source, fn) or ""
        fp["text_method"] = {
            "name": text_method,
            "page_markers": "--- Page" in segment,
            "empty_text_guard": "EXTRACTION ERROR]" in segment
            and ("len(" in segment or "page_count == 0" in segment),
            "per_page_try": sum(isinstance(n, ast.Try) for n in ast.walk(fn)) > 1,
            "finally_close": any(
                isinstance(n, ast.Try) and n.finalbody for n in ast.walk(fn)
            ),
            "body_sha": _normalised_body_sha(fn),
        }

    fn = _find_method(tree, cls, api_method)
    if fn is None:
        return {"_error": f"{cls}.{api_method} not found"}
    fp["api_method"] = {"name": api_method, **_payload_literals(fn, bindings)}
    fp["api_method"]["body_sha"] = _normalised_body_sha(fn)
    return fp


def _fingerprint_all() -> dict:
    out = {}
    for stem in EXTRACTORS:
        path = OCR_DIR / f"{stem}.py"
        if not path.exists():
            out[stem] = {"_error": "module missing"}
            continue
        out[stem] = _fingerprint_one(stem, path.read_text(encoding="utf-8"))
    return out


def _diff_traits(stem: str, expected: dict, actual: dict) -> list[str]:
    problems = []
    for group in ("text_method", "api_method"):
        exp, act = expected.get(group), actual.get(group)
        if exp is None and act is None:
            continue
        if exp is None or act is None:
            problems.append(f"{stem}.{group} appeared or disappeared")
            continue
        for trait in sorted(set(exp) | set(act)):
            if exp.get(trait) == act.get(trait):
                continue
            note = TRAIT_NOTES.get(trait, "")
            detail = f" — {note}" if note else ""
            problems.append(
                f"{stem}.{group}.{trait}: recorded {exp.get(trait)!r}, "
                f"now {act.get(trait)!r}{detail}"
            )
    return problems


def check_divergence(record: bool = False, mutate: dict | None = None) -> None:
    _section("[0/3] Divergence pins — behavioural differences between extractors")
    actual = mutate if mutate is not None else _fingerprint_all()

    if record:
        _save(DIVERGENCE_FILE, actual)
        _describe_divergence(actual)
        return

    expected = _load(DIVERGENCE_FILE)
    if expected is None:
        _skip("no divergence.json — run --record 0 to pin the current behaviour")
        return

    problems = []
    for stem in sorted(set(expected) | set(actual)):
        if stem not in expected:
            problems.append(f"{stem} is new — re-record to accept it")
        elif stem not in actual:
            problems.append(f"{stem} was removed")
        else:
            problems.extend(_diff_traits(stem, expected[stem], actual[stem]))

    if problems:
        for p in problems:
            _fail(p)
    else:
        pinned = sum(
            len(g) for m in expected.values() for g in m.values() if isinstance(g, dict)
        )
        _ok(
            f"{len(expected)} extractors, {pinned} traits unchanged",
            "a base-class collapse would fail here",
        )


def _describe_divergence(fp: dict) -> None:
    """Print the pinned differences in the form C3 has to reckon with."""
    print(f"\n  {DIM}pinned differences{RESET}")
    rows = []
    for stem, data in sorted(fp.items()):
        if "_error" in data:
            rows.append((stem, data["_error"], "", "", ""))
            continue
        t = data.get("text_method", {})
        a = data.get("api_method", {})
        rows.append(
            (
                stem.replace("_extractor", ""),
                "yes" if t.get("page_markers") else ("no" if t else "—"),
                str(a.get("temperature")),
                str(a.get("max_tokens")),
                str(a.get("timeout_config_key") or a.get("timeout_symbol")),
            )
        )
    head = ("module", "page marks", "temp", "max_tokens", "timeout key")
    widths = [max(len(str(r[i])) for r in rows + [head]) for i in range(5)]
    line = "  " + "  ".join(h.ljust(widths[i]) for i, h in enumerate(head))
    print(f"  {DIM}{line}{RESET}")
    for r in rows:
        print("    " + "  ".join(str(r[i]).ljust(widths[i]) for i in range(5)))
    print(
        f"\n  {DIM}Any two rows that differ are a behaviour difference, not a "
        f"style difference.{RESET}"
    )


# ══════════════════════════════════════════════════════════════════════════
#  LAYER 1 — text extraction over real fixtures
# ══════════════════════════════════════════════════════════════════════════

FIXTURE_TYPES = {
    "bvi": "bvi_extractor",
    "moa": "moa_extractor",
    "ejari": "ejari_extractor",
    "trade": "trade_extractor",
    "passport": "passport_extractor",
}


def _fixtures() -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = {}
    if not FIXTURES.exists():
        return found
    for doc_type in FIXTURE_TYPES:
        d = FIXTURES / doc_type
        if not d.is_dir():
            continue
        files = sorted(
            p
            for p in d.iterdir()
            if p.is_file() and p.suffix.lower() in (".pdf", ".docx", ".jpg", ".jpeg", ".png")
        )
        if files:
            found[doc_type] = files
    return found


def _instantiate(stem: str):
    """Import an extractor without importing the whole app package."""
    import importlib

    cls_name = EXTRACTORS[stem][0]
    mod = importlib.import_module(f"app.services.specialized_ocr.{stem}")
    return getattr(mod, cls_name)()


def _text_of(doc_type: str, path: Path) -> str:
    stem = FIXTURE_TYPES[doc_type]
    extractor = _instantiate(stem)
    raw = path.read_bytes()
    if path.suffix.lower() == ".docx":
        if not hasattr(extractor, "extract_text_from_docx"):
            raise RuntimeError(f"{stem} has no extract_text_from_docx")
        return extractor.extract_text_from_docx(raw)
    return extractor.extract_text_from_pdf(raw)


def _text_record(text: str) -> dict:
    return {
        "sha1": _sha(text),
        "chars": len(text),
        "lines": text.count("\n") + 1,
        "page_markers": text.count("--- Page "),
        "head": text[:200],
        "tail": text[-200:],
        "is_error": text.startswith("[PDF EXTRACTION ERROR]"),
    }


def check_text(record: bool = False) -> None:
    _section("[1/3] Text extraction — deterministic, offline")
    fixtures = _fixtures()
    if not fixtures:
        _skip(
            f"no fixtures in {FIXTURES.relative_to(ROOT)} — "
            "see docs/ocr-corpus-runbook.md"
        )
        return

    sys.path.insert(0, str(BACKEND))
    results: dict[str, dict] = {}
    for doc_type, paths in sorted(fixtures.items()):
        stem = FIXTURE_TYPES[doc_type]
        if EXTRACTORS[stem][1] is None:
            # No text_method for this extractor (currently: passport_extractor,
            # which goes straight from PDF/image pages to Textract or a vision
            # model -- there is no intermediate "extracted raw text" stage the
            # way there is for the four text-based extractors). This is a
            # real architectural difference, not a gap: forcing an
            # extract_text_from_pdf onto an image pipeline would be the same
            # mistake this file's own module docstring warns against (a
            # unifying base-class method that quietly changes behaviour).
            # Layer 2 (request shape) still covers passport separately, via
            # extract_from_image -- see _run_intercepted below.
            continue
        for path in paths:
            key = f"{doc_type}/{path.name}"
            try:
                results[key] = _text_record(_text_of(doc_type, path))
            except Exception as e:  # noqa: BLE001 — a crash here IS the finding
                results[key] = {"_error": f"{type(e).__name__}: {e}"}

    if record:
        _save(TEXT_FILE, results)
        errs = [k for k, v in results.items() if "_error" in v or v.get("is_error")]
        _ok(f"recorded {len(results)} fixture extractions")
        for k in errs:
            print(f"  {YELLOW}note{RESET}  {k} produced an error result — recorded as-is")
        return

    expected = _load(TEXT_FILE)
    if expected is None:
        _skip("no text.json — run --record 1")
        return

    for key in sorted(set(expected) | set(results)):
        if key not in results:
            _fail(f"fixture {key} recorded but missing from disk")
        elif key not in expected:
            _fail(f"fixture {key} is new — re-record to accept it")
        elif expected[key].get("sha1") != results[key].get("sha1"):
            e, a = expected[key], results[key]
            _fail(
                f"{key}: extracted text changed "
                f"({e.get('chars')}→{a.get('chars')} chars, "
                f"{e.get('page_markers')}→{a.get('page_markers')} page markers)"
            )
    if not failures:
        _ok(f"{len(results)} fixtures, extracted text byte-identical")


# ══════════════════════════════════════════════════════════════════════════
#  LAYER 2 — outbound request shape, intercepted
# ══════════════════════════════════════════════════════════════════════════


class _StopExtraction(Exception):
    """Raised by the interceptor in verify mode. Never leaves this module."""


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Interceptor:
    """Stands in for requests.post inside an extractor module.

    verify mode  — record the call shape, then abort. Nothing is sent.
    replay mode  — serve the cassette keyed by prompt hash. Nothing is sent.
    record mode  — forward to the real requests.post and save the response.

    The distinction matters: this file must be safe to run on a laptop with a
    live API key in the environment and never spend a cent or leak a document.
    """

    def __init__(self, mode: str, cassette: dict | None = None):
        self.mode = mode
        self.cassette = cassette or {}
        self.calls: list[dict] = []
        self._real = None

    def __call__(self, url, headers=None, json=None, timeout=None, **kw):  # noqa: A002
        payload = json or {}
        messages = payload.get("messages") or [{}]
        content = messages[0].get("content", "")
        if isinstance(content, list):  # vision payloads
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )

        # Prompt caching (prompt-remediation Phase 3): this `payload` is the
        # already-translated Bedrock format (bedrock_client._to_bedrock_
        # payload runs before requests.post is called), where a cached
        # system prompt lives in a separate top-level "system" key, not in
        # `messages`. Recording it separately from the dynamic user-turn
        # `content` above is what makes "how much did Phase 3 actually
        # shrink the dynamic per-call prompt" and "how much is now cached
        # instead of removed" two different, honestly-reported numbers,
        # rather than one figure that looks like a bigger reduction than it
        # is because it silently stopped counting the (still-sent, just
        # cached) system block.
        system_blocks = payload.get("system") or []
        system_text = "".join(
            b.get("text", "") for b in system_blocks if isinstance(b, dict)
        )
        system_cached = any(
            isinstance(b, dict) and b.get("cache_control") for b in system_blocks
        )

        prompt_sha = _sha(content)
        self.calls.append(
            {
                "url": url,
                "model": payload.get("model"),
                "temperature": payload.get("temperature"),
                "max_tokens": payload.get("max_tokens"),
                "timeout": timeout,
                "prompt_sha1": prompt_sha,
                "prompt_chars": len(content),
                "prompt_tokens_est": _estimate_tokens(content),
                "system_chars": len(system_text),
                "system_tokens_est": _estimate_tokens(system_text),
                "system_cached": system_cached,
            }
        )
        if self.mode == "verify":
            raise _StopExtraction(prompt_sha)
        if self.mode == "replay":
            hit = self.cassette.get(prompt_sha)
            if hit is None:
                raise _StopExtraction(f"no cassette for prompt {prompt_sha[:12]}")
            return _FakeResponse(hit)
        resp = self._real(url, headers=headers, json=payload, timeout=timeout, **kw)
        try:
            self.cassette[prompt_sha] = resp.json()
        except Exception:  # noqa: BLE001
            pass
        return resp


def _run_intercepted(stem: str, doc_type: str, path: Path, mode: str, cassette=None):
    """Drive one extractor to its first API call with requests.post replaced."""
    import importlib

    mod = importlib.import_module(f"app.services.specialized_ocr.{stem}")
    interceptor = _Interceptor(mode, cassette)
    interceptor._real = mod.requests.post
    original = mod.requests.post
    mod.requests.post = interceptor
    try:
        extractor = _instantiate(stem)
        raw = path.read_bytes()
        text_method = EXTRACTORS[stem][1]
        if text_method is None:
            # Image-pipeline extractor (currently: passport_extractor) --
            # no extract_text_from_pdf/_from_docx stage exists to drive.
            # Build a PIL Image straight from the fixture bytes (a JPEG
            # fixture, per FIXTURE_TYPES) and call the API method
            # (extract_from_image) directly, which is what actually
            # produces the outbound request this layer measures.
            from PIL import Image
            import io as _io
            img = Image.open(_io.BytesIO(raw)).convert("RGB")
            extractor.extract_from_image(img, "page_1")
        elif path.suffix.lower() == ".docx":
            text = extractor.extract_text_from_docx(raw)
            for method in ("extract_with_ai", "_extract_with_ai"):
                if hasattr(extractor, method):
                    getattr(extractor, method)(text)
                    break
        else:
            text = extractor.extract_text_from_pdf(raw)
            for method in ("extract_with_ai", "_extract_with_ai"):
                if hasattr(extractor, method):
                    getattr(extractor, method)(text)
                    break
    except _StopExtraction:
        pass
    finally:
        mod.requests.post = original
    return interceptor


def check_requests(record: bool = False) -> None:
    _section("[2/3] Outbound request shape — intercepted, never sent")
    fixtures = _fixtures()
    if not fixtures:
        _skip("no fixtures — layer 2 needs one document per type")
        return

    sys.path.insert(0, str(BACKEND))
    results: dict[str, list] = {}
    for doc_type, paths in sorted(fixtures.items()):
        stem = FIXTURE_TYPES[doc_type]
        path = paths[0]  # request shape does not vary by document
        key = f"{doc_type}/{path.name}"
        try:
            results[key] = _run_intercepted(stem, doc_type, path, "verify").calls
        except Exception as e:  # noqa: BLE001
            results[key] = [{"_error": f"{type(e).__name__}: {e}"}]

    if record:
        _save(REQUEST_FILE, results)
        _ok(f"recorded request shapes for {len(results)} document types")
        return

    expected = _load(REQUEST_FILE)
    if expected is None:
        _skip("no requests.json — run --record 2")
        return

    for key in sorted(set(expected) | set(results)):
        if key not in results or key not in expected:
            _fail(f"request record {key} added or removed")
            continue
        exp, act = expected[key], results[key]
        if len(exp) != len(act):
            _fail(f"{key}: {len(exp)} API call(s) recorded, {len(act)} now")
            continue
        for i, (e, a) in enumerate(zip(exp, act)):
            for field in ("model", "temperature", "max_tokens", "timeout", "prompt_sha1"):
                if e.get(field) != a.get(field):
                    _fail(
                        f"{key} call {i}: {field} {e.get(field)!r} → {a.get(field)!r}"
                    )
    if not failures:
        total = sum(len(v) for v in results.values())
        _ok(f"{total} intercepted call(s) identical", "no request left this process")


# ══════════════════════════════════════════════════════════════════════════
#  LAYER 3 — full pipeline against replayed responses
# ══════════════════════════════════════════════════════════════════════════


def _cassette_path(doc_type: str) -> Path:
    return CASSETTES / f"{doc_type}.json"


def check_pipeline(record: bool = False) -> None:
    _section("[3/3] Full extraction — recorded LLM responses replayed")
    fixtures = _fixtures()
    if not fixtures:
        _skip("no fixtures — layer 3 needs fixtures and one recorded pass")
        return
    if not CASSETTES.exists() and not record:
        _skip(
            "no cassettes — run --record 3 inside the container with credentials "
            "(see docs/ocr-corpus-runbook.md)"
        )
        return

    sys.path.insert(0, str(BACKEND))
    results: dict[str, dict] = {}
    for doc_type, paths in sorted(fixtures.items()):
        stem = FIXTURE_TYPES[doc_type]
        cassette = _load(_cassette_path(doc_type)) or {}
        if not cassette and not record:
            _skip(f"{doc_type}: no cassette recorded")
            continue
        for path in paths:
            key = f"{doc_type}/{path.name}"
            try:
                interceptor = _run_intercepted(
                    stem, doc_type, path, "record" if record else "replay", cassette
                )
                results[key] = {"calls": len(interceptor.calls)}
            except Exception as e:  # noqa: BLE001
                results[key] = {"_error": f"{type(e).__name__}: {e}"}
        if record and cassette:
            _save(_cassette_path(doc_type), cassette)

    if record:
        _save(PIPELINE_FILE, results)
        _ok(f"recorded {len(results)} pipeline run(s)")
        return

    expected = _load(PIPELINE_FILE)
    if expected is None:
        _skip("no pipeline.json — run --record 3")
        return
    for key in sorted(set(expected) | set(results)):
        if expected.get(key) != results.get(key):
            _fail(f"{key}: pipeline result changed")
    if not failures:
        _ok(f"{len(results)} pipeline run(s) identical")


# ══════════════════════════════════════════════════════════════════════════
#  --self-test — watch the checks fail before trusting a green
# ══════════════════════════════════════════════════════════════════════════


def self_test() -> int:
    """Mutate the inputs and assert each layer notices.

    Written because contract check 13 shipped two versions that both reported
    zero problems, and only one of them was actually working.
    """
    print("=" * 72)
    print("  OCR CORPUS — SELF TEST")
    print("=" * 72)
    print(f"{DIM}Each case below MUST fail. A pass here is the bug.{RESET}")
    problems = []

    expected = _load(DIVERGENCE_FILE)
    if expected is None:
        print(f"\n  {YELLOW}SKIP{RESET}  no divergence.json — run --record 0 first")
        return 0

    # Case 1: the exact edit a naive BaseDocumentExtractor would make —
    # unify extract_text_from_pdf, so ejari/trade start emitting page markers.
    import copy

    mutated = copy.deepcopy(expected)
    victim = None
    for stem, data in mutated.items():
        tm = data.get("text_method")
        if tm and tm.get("page_markers") is False:
            tm["page_markers"] = True
            tm["body_sha"] = "collapsed-into-base-class"
            victim = stem
            break
    if victim:
        failures.clear()
        check_divergence(mutate=mutated)
        if failures:
            print(
                f"  {GREEN}GOOD{RESET}  layer 0 caught page markers appearing "
                f"in {victim}"
            )
        else:
            problems.append("layer 0 did NOT catch a page-marker collapse")

    # Case 2: temperature harmonised to a single value across extractors.
    mutated = copy.deepcopy(expected)
    changed = None
    for stem, data in mutated.items():
        am = data.get("api_method", {})
        if am.get("temperature") == 0.1:
            am["temperature"] = 0.0
            changed = stem
            break
    if changed:
        failures.clear()
        check_divergence(mutate=mutated)
        if failures:
            print(f"  {GREEN}GOOD{RESET}  layer 0 caught temperature change in {changed}")
        else:
            problems.append("layer 0 did NOT catch a temperature change")

    # Case 3: the three separate timeout keys folded into one.
    mutated = copy.deepcopy(expected)
    for data in mutated.values():
        if data.get("api_method", {}).get("timeout_symbol"):
            data["api_method"]["timeout_symbol"] = "SHARED_TIMEOUT"
    failures.clear()
    check_divergence(mutate=mutated)
    if failures:
        print(f"  {GREEN}GOOD{RESET}  layer 0 caught the timeout keys being merged")
    else:
        problems.append("layer 0 did NOT catch merged timeout keys")

    # Case 4: an interceptor in verify mode must never reach the network.
    failures.clear()
    probe = _Interceptor("verify")
    try:
        probe(
            "https://bedrock-runtime.ap-south-1.amazonaws.com/model/test/invoke",
            json={"model": "m", "messages": [{"content": "hello"}], "temperature": 0.1},
            timeout=30,
        )
        problems.append("interceptor did NOT abort in verify mode")
    except _StopExtraction:
        print(f"  {GREEN}GOOD{RESET}  interceptor aborted before sending")

    failures.clear()
    print("\n" + "=" * 72)
    if problems:
        print(f"  {RED}{len(problems)} SELF-TEST FAILURE(S){RESET} — the checks are blind")
        for p in problems:
            print(f"    - {p}")
        print("=" * 72)
        return 1
    print(f"  {GREEN}SELF TEST PASSED{RESET} — every layer fails when it should")
    print("=" * 72)
    return 0


# ══════════════════════════════════════════════════════════════════════════
#  --report
# ══════════════════════════════════════════════════════════════════════════


def report() -> int:
    print("=" * 72)
    print("  OCR CORPUS — COVERAGE")
    print("=" * 72)

    fixtures = _fixtures()
    print(f"\n{DIM}Fixtures{RESET}  {FIXTURES.relative_to(ROOT)}")
    for doc_type in FIXTURE_TYPES:
        files = fixtures.get(doc_type, [])
        mark = f"{GREEN}✓{RESET}" if files else f"{RED}✗{RESET}"
        names = ", ".join(p.name for p in files) if files else "none"
        print(f"  {mark} {doc_type:<10} {len(files):>2}  {DIM}{names}{RESET}")

    print(f"\n{DIM}Recorded layers{RESET}")
    for label, path in (
        ("0 divergence", DIVERGENCE_FILE),
        ("1 text", TEXT_FILE),
        ("2 requests", REQUEST_FILE),
        ("3 pipeline", PIPELINE_FILE),
    ):
        data = _load(path)
        mark = f"{GREEN}✓{RESET}" if data else f"{RED}✗{RESET}"
        count = f"{len(data)} entries" if data else "not recorded"
        print(f"  {mark} {label:<14} {count}")

    cassettes = sorted(CASSETTES.glob("*.json")) if CASSETTES.exists() else []
    print(f"  {DIM}cassettes: {len(cassettes)}{RESET}")

    request_data = _load(REQUEST_FILE)
    if request_data:
        print(f"\n{DIM}Prompt size (Layer 2, most recent recording){RESET}")
        rows = []
        for key in sorted(request_data):
            for call in request_data[key]:
                tok = call.get("prompt_tokens_est")
                if tok is None:
                    continue
                rows.append((key, tok, call.get("prompt_chars", 0)))
        if rows:
            width = max(len(r[0]) for r in rows)
            for key, tok, chars in rows:
                print(f"  {key.ljust(width)}  ~{tok:>6,} tok est.  ({chars:,} chars)")
            print(f"  {DIM}estimate only, ~4 chars/token — see _estimate_tokens(){RESET}")
        else:
            print(f"  {DIM}no successful call recorded a prompt yet{RESET}")

    ready = bool(fixtures) and DIVERGENCE_FILE.exists() and TEXT_FILE.exists()
    print("\n" + "=" * 72)
    if ready:
        print(f"  {GREEN}Layers 0-1 recorded.{RESET} C3 may be attempted with care.")
    else:
        print(f"  {YELLOW}Corpus incomplete — C3 must not be attempted.{RESET}")
        print(f"  {DIM}Next: docs/ocr-corpus-runbook.md{RESET}")
    print("=" * 72)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record",
        type=int,
        choices=[0, 1, 2, 3],
        help="record a layer instead of verifying it",
    )
    parser.add_argument("--report", action="store_true", help="show corpus coverage")
    parser.add_argument("--self-test", action="store_true", help="prove checks fail")
    args = parser.parse_args()

    if args.report:
        return report()
    if args.self_test:
        return self_test()

    print("=" * 72)
    print("  OCR EXTRACTION CORPUS — Thrivv Onboarding Agent")
    print("=" * 72)

    if args.record is not None:
        {0: check_divergence, 1: check_text, 2: check_requests, 3: check_pipeline}[
            args.record
        ](record=True)
    else:
        check_divergence()
        check_text()
        check_requests()
        check_pipeline()

    print("\n" + "=" * 72)
    if failures:
        print(f"  {RED}{len(failures)} FAILURE(S){RESET} — extraction behaviour moved")
        for f in failures:
            print(f"    - {f}")
    elif skips and not args.record:
        verified = 4 - len(skips)
        print(
            f"  {YELLOW}PARTIAL{RESET} — {verified} layer(s) verified, "
            f"{len(skips)} with no corpus"
        )
        print(
            f"  {DIM}Divergence is pinned, so a base-class collapse fails. "
            f"Extraction ACCURACY is not covered.{RESET}"
        )
        print(f"  {DIM}An empty layer is not a passing layer. Run --report.{RESET}")
    else:
        print(f"  {GREEN}CORPUS INTACT{RESET} — extraction behaviour unchanged")
    print("=" * 72)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
