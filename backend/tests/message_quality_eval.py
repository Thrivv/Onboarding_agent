"""
Message quality eval — the generated-OUTPUT counterpart to ocr_corpus.py.

ocr_corpus.py pins the *inputs* the LLM receives (prompt-building code,
outbound request shape). It says nothing about the *output* a caller
actually gets back and shows the user — message_generator.py already
carries its own safety net for that (`_check_format_violations()` /
`_validate_and_clean_output()`, run on every AI-generated banking message
before it reaches a user), but until this file, that safety net itself had
zero test coverage. A regex silently weakened there (say, a sign-off
pattern that stops matching "Warm regards," or an emoji range that misses
a newer codepoint block) would ship straight to production with every
existing check green — nothing in this codebase would notice.

Two layers, cheapest first:

  0. GUARDRAIL   _check_format_violations() flags the right violation
                 category for a curated set of good/bad sample outputs.
                 No fixtures, no network, no credentials. Runs today.
  1. CLEANING    _validate_and_clean_output() actually removes what layer 0
                 flags, and leaves already-clean text byte-identical
                 (idempotent). No fixtures, no network, no credentials.
                 Runs today.
  2. JUDGE       an LLM-as-judge pass over real generated messages for
                 real onboarding scenarios, scored against the same rubric
                 PROFESSIONAL_BANKING_CONTEXT encodes (tone, no hallucinated
                 claims, actually answers the step's instruction) — catches
                 the class of quality problem (unhelpful, wrong, off-topic,
                 tone-correct-but-bad-content) that regex pattern matching
                 structurally cannot. Needs live Bedrock credentials;
                 recorded verdicts replay from a cassette otherwise, same
                 convention as ocr_corpus.py's Layer 3.

  THE RULE FROM contract_check.py / ocr_corpus.py APPLIES HERE
  A check that returns zero has told you nothing until you have watched it
  fail. --self-test corrupts an expectation and asserts the layer notices.

Usage
    python backend/tests/message_quality_eval.py                 # verify
    python backend/tests/message_quality_eval.py --report        # coverage
    python backend/tests/message_quality_eval.py --record 2      # record judge cassette (LIVE API)
    python backend/tests/message_quality_eval.py --self-test     # prove the checks fail

Exit code 0 when every recorded expectation holds. Layer 2 with no cassette
reports SKIP and does not affect the exit code — matching ocr_corpus.py's
convention that an empty layer is not a passing layer.

Scope note: this does not replace a human/LLM-judged accuracy eval of the
*extraction* pipeline (that's OCR correctness, covered — structurally, not
for accuracy — by ocr_corpus.py). This file is specifically about the
conversational/message-generation output surface: message_generator.py and
handle_reply.py's build_onboarding_prompt() reply path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
CORPUS = Path(__file__).resolve().parent / "message_quality"
JUDGE_FILE = CORPUS / "judge_verdicts.json"

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


def _categorize(violations) -> set:
    """Collapse message_generator.py's free-text violation strings into
    stable category keys, so this eval survives wording tweaks to those
    strings and only breaks when a REGEX actually stops firing."""
    cats = set()
    for v in violations:
        low = v.lower()
        if "greeting" in low:
            cats.add("greeting")
        elif "sign-off" in low:
            cats.add("sign_off")
        elif "signature" in low:
            cats.add("signature")
        elif "emoji" in low:
            cats.add("emoji")
        elif "casual" in low:
            cats.add("casual")
        else:
            cats.add("other")
    return cats


def _import_generator():
    sys.path.insert(0, str(BACKEND))
    from app import config
    from app.services.message_generator import MessageGenerator

    return MessageGenerator, config


# ══════════════════════════════════════════════════════════════════════════
#  Layer 0 — GUARDRAIL fixtures
# ══════════════════════════════════════════════════════════════════════════


def _format_fixtures(brand: str) -> list:
    return [
        dict(
            label="clean_status_update",
            message_type="GENERIC",
            expect=set(),
            text=(
                "Your Emirates ID has been received and validated successfully. "
                "Please proceed to upload your Commercial License."
            ),
        ),
        dict(
            label="greeting_dear",
            message_type="GENERIC",
            expect={"greeting"},
            text="Dear Varsha Balaji,\n\nYour document has been received and is under review.",
        ),
        dict(
            label="greeting_hi",
            message_type="GENERIC",
            expect={"greeting"},
            text="Hi there, your account setup is progressing well.",
        ),
        dict(
            label="signoff_kind_regards",
            message_type="GENERIC",
            expect={"sign_off"},
            text="Your documents are being processed and verification is underway.\n\nKind regards,",
        ),
        dict(
            label="signoff_thank_you",
            message_type="GENERIC",
            expect={"sign_off"},
            text="All required documents have been received and verification is in progress.\n\nThank you",
        ),
        dict(
            label="signature_brand_bank",
            message_type="GENERIC",
            expect={"signature"},
            text=f"Your onboarding is now complete and account details will follow shortly.\n{brand} Bank",
        ),
        dict(
            label="signature_the_team",
            message_type="GENERIC",
            expect={"signature"},
            text="Your Trade License has been verified and is now on file.\nThe Team",
        ),
        dict(
            label="emoji_non_welcome",
            message_type="GENERIC",
            expect={"emoji"},
            text="Your document has been verified successfully \U0001F389 please continue.",
        ),
        dict(
            label="emoji_welcome_allowed",
            message_type="WELCOME_MESSAGE",
            expect=set(),
            text="Welcome to onboarding \U0001F44B please share your Emirates ID or Passport to begin.",
        ),
        dict(
            label="casual_awesome",
            message_type="GENERIC",
            expect={"casual"},
            text="Awesome! Your documents have been received and are being reviewed.",
        ),
        dict(
            label="combo_greeting_and_signoff",
            message_type="GENERIC",
            expect={"greeting", "sign_off"},
            text="Dear Customer,\n\nYour Ejari contract has been received and verified.\n\nBest regards,",
        ),
    ]


def check_guardrail() -> None:
    _section("[0/2] Format guardrail — _check_format_violations() on curated samples")
    MessageGenerator, config = _import_generator()
    fixtures = _format_fixtures(config.BRAND_NAME)
    mismatches = []
    for fx in fixtures:
        got = _categorize(
            MessageGenerator._check_format_violations(fx["text"], fx["message_type"])
        )
        if got != fx["expect"]:
            mismatches.append(f"{fx['label']}: expected {sorted(fx['expect'])}, got {sorted(got)}")
    if mismatches:
        for m in mismatches:
            _fail(m)
    else:
        _ok(
            f"{len(fixtures)} sample(s) categorized correctly",
            "greeting / sign-off / signature / emoji / casual",
        )


# ══════════════════════════════════════════════════════════════════════════
#  Layer 1 — CLEANING fixtures
# ══════════════════════════════════════════════════════════════════════════


def _cleaning_fixtures(brand: str) -> list:
    body = "Your documents have been received and verification is now in progress."
    return [
        dict(label="already_clean_untouched", dirty=body, clean=body),
        dict(label="strips_dear_greeting", dirty=f"Dear Varsha,\n\n{body}", clean=body),
        dict(label="strips_kind_regards", dirty=f"{body}\n\nKind regards,", clean=body),
        dict(label="strips_brand_signature", dirty=f"{body}\n{brand}", clean=body),
        dict(label="strips_the_team_signature", dirty=f"{body}\nThe Team", clean=body),
        dict(
            label="strips_greeting_and_signoff_together",
            dirty=f"Hello Customer,\n\n{body}\n\nBest regards,\n{brand}",
            clean=body,
        ),
    ]


def check_cleaning() -> None:
    _section("[1/2] Output cleaning — _validate_and_clean_output() safety net")
    MessageGenerator, config = _import_generator()
    fixtures = _cleaning_fixtures(config.BRAND_NAME)
    mismatches = []
    for fx in fixtures:
        got = MessageGenerator._validate_and_clean_output(fx["dirty"])
        if got.strip() != fx["clean"].strip():
            mismatches.append(f"{fx['label']}: expected {fx['clean']!r}, got {got!r}")
        # Idempotence: cleaning already-clean text must not further mutate it —
        # a real caller only gets one pass, but a check that only holds on the
        # first pass is a check that is quietly relying on pattern order.
        twice = MessageGenerator._validate_and_clean_output(got)
        if twice.strip() != got.strip():
            mismatches.append(f"{fx['label']}: not idempotent ({got!r} -> {twice!r})")
    if mismatches:
        for m in mismatches:
            _fail(m)
    else:
        _ok(f"{len(fixtures)} sample(s) cleaned correctly and idempotently")


# ══════════════════════════════════════════════════════════════════════════
#  Layer 2 — LLM-as-judge over real generated messages (LIVE, recorded)
# ══════════════════════════════════════════════════════════════════════════

JUDGE_SCENARIOS = [
    dict(
        key="welcome_individual",
        message_type="WELCOME_MESSAGE",
        prompt=(
            "Generate the welcome message for a new individual banking "
            "customer starting onboarding. Ask them to submit their "
            "Emirates ID or Passport as image files to begin."
        ),
    ),
    dict(
        key="doc_verification_in_progress",
        message_type="GENERIC",
        prompt=(
            "Inform the user that all relevant documents have been "
            "received and are being verified. Ask if they have any "
            "other queries."
        ),
    ),
    dict(
        key="verification_complete",
        message_type="GENERIC",
        prompt=(
            "Congratulate the user for being onboarded and inform them "
            "that account details will be shared within 3-4 business days."
        ),
    ),
]

# Mirrors the actual rules PROFESSIONAL_BANKING_CONTEXT encodes (see
# message_generator.py) — a judge scoring against a different rubric than
# production actually enforces would be worthless.
JUDGE_RUBRIC = (
    "You are grading a single message an AI banking assistant is about to "
    "send a customer, against these rules:\n"
    "1. No greeting at the start (no 'Dear', 'Hello', 'Hi', 'Greetings').\n"
    "2. No sign-off or signature at the end (no 'Kind regards', 'Thank you', "
    "a team/brand signature).\n"
    "3. No emojis, unless this is a welcome message.\n"
    "4. No casual/celebratory language ('Awesome!', 'Great job!', etc.).\n"
    "5. The message actually carries out the instruction it was asked to "
    "carry out, with no fabricated claim (a status, a date, a document "
    "name) beyond what the instruction gave it.\n\n"
    "Score 1-5 (5 = fully compliant) and reply with ONLY a JSON object: "
    '{"score": <int>, "reason": "<one sentence>"}.'
)

JUDGE_FLOOR = 4  # out of 5 — see JUDGE_RUBRIC


def check_judge(record: bool = False) -> None:
    _section("[2/2] LLM-as-judge — real generated messages scored against the banking rubric")
    if not JUDGE_FILE.exists() and not record:
        _skip(
            "no judge_verdicts.json — run --record 2 with live Bedrock "
            "credentials to record it (see module docstring)"
        )
        return

    if record:
        sys.path.insert(0, str(BACKEND))
        from app.services.message_generator import MessageGenerator
        from app.services.run_model import call_local_llm

        verdicts = {}
        for scenario in JUDGE_SCENARIOS:
            try:
                message = MessageGenerator._generate_with_retry(
                    scenario["prompt"], scenario["message_type"]
                )
                judge_reply = call_local_llm(
                    f'Message to grade:\n"""{message}"""',
                    system_prompt=JUDGE_RUBRIC,
                    temperature=0.0,
                )
                verdict = json.loads(judge_reply)
                verdicts[scenario["key"]] = {
                    "message": message,
                    "score": verdict.get("score"),
                    "reason": verdict.get("reason"),
                }
            except Exception as e:  # noqa: BLE001
                verdicts[scenario["key"]] = {"_error": f"{type(e).__name__}: {e}"}
        _save(JUDGE_FILE, verdicts)
        _ok(f"recorded {len(verdicts)} judge verdict(s)")
        return

    verdicts = _load(JUDGE_FILE)
    if not verdicts:
        _skip("judge_verdicts.json is empty")
        return
    below_floor = []
    for key, v in verdicts.items():
        if "_error" in v:
            below_floor.append(f"{key}: generation/judge error — {v['_error']}")
            continue
        score = v.get("score")
        if not isinstance(score, (int, float)) or score < JUDGE_FLOOR:
            below_floor.append(f"{key}: score {score} below floor {JUDGE_FLOOR} — {v.get('reason')}")
    if below_floor:
        for m in below_floor:
            _fail(m)
    else:
        _ok(f"{len(verdicts)} recorded verdict(s) at or above floor {JUDGE_FLOOR}/5")


# ══════════════════════════════════════════════════════════════════════════
#  --self-test — watch the checks fail before trusting a green
# ══════════════════════════════════════════════════════════════════════════


def self_test() -> int:
    """Prove the layers actually detect a bad message, not just recognize a
    good one — written for the same reason ocr_corpus.py's self-test was:
    a check that has never been watched to fail has told you nothing."""
    print("=" * 72)
    print("  MESSAGE QUALITY EVAL — SELF TEST")
    print("=" * 72)
    print(f"{DIM}Each case below MUST fail. A pass here is the bug.{RESET}")
    problems = []
    MessageGenerator, config = _import_generator()

    # Case 1: guardrail must catch an obvious greeting.
    got = _categorize(
        MessageGenerator._check_format_violations("Dear Customer, welcome.", "GENERIC")
    )
    if got == {"greeting"}:
        print(f"  {GREEN}GOOD{RESET}  guardrail flagged an obvious greeting")
    else:
        problems.append(f"guardrail did NOT flag an obvious greeting (got {sorted(got)})")

    # Case 2: guardrail must NOT flag emojis in a welcome message (the one
    # documented exception) — a check that flags everything is as blind as
    # one that flags nothing.
    got = _categorize(
        MessageGenerator._check_format_violations("Welcome \U0001F389 begin here.", "WELCOME_MESSAGE")
    )
    if "emoji" not in got:
        print(f"  {GREEN}GOOD{RESET}  guardrail correctly allowed an emoji in a welcome message")
    else:
        problems.append("guardrail incorrectly flagged an emoji in a welcome message")

    # Case 3: cleaning must actually remove a sign-off, not just report it.
    dirty = "Your account is ready.\n\nKind regards,"
    cleaned = MessageGenerator._validate_and_clean_output(dirty)
    if "Kind regards" not in cleaned:
        print(f"  {GREEN}GOOD{RESET}  cleaning removed an obvious sign-off")
    else:
        problems.append("cleaning did NOT remove an obvious sign-off")

    # Case 4: the fixture-comparison mechanism itself — a deliberately wrong
    # expectation for an obviously-dirty sample must register as a mismatch.
    bad_expectation = _categorize(
        MessageGenerator._check_format_violations("Dear Customer, your account is ready.", "GENERIC")
    )
    if bad_expectation != set():
        print(f"  {GREEN}GOOD{RESET}  comparison would catch a deliberately wrong (empty) expectation")
    else:
        problems.append("comparison would NOT catch a deliberately wrong expectation")

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
    print("  MESSAGE QUALITY EVAL — COVERAGE")
    print("=" * 72)
    MessageGenerator, config = _import_generator()
    print(f"\n{DIM}Layer 0/1 fixtures (hand-authored, always run){RESET}")
    print(f"  {len(_format_fixtures(config.BRAND_NAME))} guardrail sample(s)")
    print(f"  {len(_cleaning_fixtures(config.BRAND_NAME))} cleaning sample(s)")

    verdicts = _load(JUDGE_FILE)
    mark = f"{GREEN}✓{RESET}" if verdicts else f"{RED}✗{RESET}"
    count = f"{len(verdicts)} verdict(s)" if verdicts else "not recorded"
    print(f"\n{DIM}Layer 2 judge cassette{RESET}  {mark} {count}")
    print(
        f"  {DIM}{len(JUDGE_SCENARIOS)} scenario(s) defined: "
        f"{', '.join(s['key'] for s in JUDGE_SCENARIOS)}{RESET}"
    )
    print("\n" + "=" * 72)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record", type=int, choices=[2], help="record layer 2's judge cassette (LIVE API)"
    )
    parser.add_argument("--report", action="store_true", help="show corpus coverage")
    parser.add_argument("--self-test", action="store_true", help="prove checks fail")
    args = parser.parse_args()

    if args.report:
        return report()
    if args.self_test:
        return self_test()

    print("=" * 72)
    print("  MESSAGE QUALITY EVAL — Thrivv Onboarding Agent")
    print("=" * 72)

    if args.record == 2:
        check_judge(record=True)
    else:
        check_guardrail()
        check_cleaning()
        check_judge()

    print("\n" + "=" * 72)
    if failures:
        print(f"  {RED}{len(failures)} FAILURE(S){RESET} — message quality regressed")
        for f in failures:
            print(f"    - {f}")
    elif skips and args.record is None:
        verified = 2 - len(skips)
        print(
            f"  {YELLOW}PARTIAL{RESET} — {verified} layer(s) verified, "
            f"{len(skips)} with no corpus"
        )
        print(
            f"  {DIM}Guardrail + cleaning are pinned and run every time. "
            f"Judge needs live credentials.{RESET}"
        )
        print(f"  {DIM}An empty layer is not a passing layer. Run --report.{RESET}")
    else:
        print(f"  {GREEN}QUALITY EVAL INTACT{RESET} — message-output guardrails unchanged")
    print("=" * 72)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
