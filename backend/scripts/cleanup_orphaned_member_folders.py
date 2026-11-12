#!/usr/bin/env python3
"""
cleanup_orphaned_member_folders.py

One-off repair for the two folder-layout bugs fixed in /ki/add-ai and the
SO-AS handler (app/api/routes/chatupload.py):

  1. Orphaned root-level identity folders — e.g. documents/id/{ref_no}/EID-{ref_no}/
     or .../PP-{ref_no}/ — created when an EID/Passport was uploaded via the
     "Add another AS/KI?" loop (is_ki_loop_add_eid=true). These were supposed
     to be moved into members/{PREFIX}-{ref_no}-{index}/ by /ki/add-ai, but the
     old code only *copied* them into a legacy {ref_no}/{display_name}/ folder
     and never removed the original — leaving a duplicate at the root.

  2. Legacy per-name folders — e.g. documents/id/{ref_no}/VARSHA BALAJI BALAJI/ —
     pre-created by mkdir() calls that have since been removed. Almost always
     empty; occasionally hold a duplicate copy from bug #1 above.

By default this script only REPORTS what it finds (dry run). Pass --apply to
actually make changes. Pass a ref_no as the first positional arg to limit the
scan to a single onboarding folder.

Usage:
    python scripts/cleanup_orphaned_member_folders.py                # dry run, all ref_nos
    python scripts/cleanup_orphaned_member_folders.py 2ad30133-...   # dry run, one ref_no
    python scripts/cleanup_orphaned_member_folders.py --apply        # actually fix, all ref_nos
    python scripts/cleanup_orphaned_member_folders.py 2ad30133-... --apply
"""

import sys
import json
import shutil
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.document_helpers import get_documents_base_path

# Prefixes that are legitimate NON-member top-level document folders — never touched.
BUSINESS_DOC_PREFIXES = ("TL-", "POS-", "MOA-", "DOC-")
# Prefixes that mean "identity document" — these are the ones that should
# live under members/, never bare at the root.
IDENTITY_PREFIXES = ("EID-", "PP-")


def _load_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _extracted_id_number(output_data: dict) -> str:
    if not output_data:
        return ""
    fields = output_data.get("extracted_fields") or {}
    return (fields.get("ID Number") or fields.get("Passport Number") or "").strip().upper()


def _extracted_name(output_data: dict) -> str:
    if not output_data:
        return ""
    fields = output_data.get("extracted_fields") or {}
    return (fields.get("Name") or "").strip().upper()


def _scan_members_dir(members_dir: Path):
    """Return list of (folder_path, output_data) for every doc already under members/."""
    results = []
    if not members_dir.exists():
        return results
    for folder in members_dir.iterdir():
        if not folder.is_dir():
            continue
        oj = _load_json(folder / "output.json")
        if oj:
            results.append((folder, oj))
    return results


def _next_member_index(members_dir: Path) -> int:
    if not members_dir.exists():
        return 1
    existing = [d for d in members_dir.iterdir() if d.is_dir()]
    return len(existing) + 1


def _move_into_members(src_dir: Path, members_dir: Path, member_name: str, apply: bool, report: list):
    """Move src_dir's contents into members/{prefix}-{ref_no}-{idx}/, renaming file + patching output.json."""
    oj = _load_json(src_dir / "output.json")
    doc_type = ((oj or {}).get("document_type") or "eid").lower().strip()
    prefix = "PP-" if doc_type == "passport" else "MEID-"

    ref_no = members_dir.parent.name
    idx = _next_member_index(members_dir)
    proper_id = f"{prefix}{ref_no}-{idx}"
    dst_dir = members_dir / proper_id

    report.append(f"    → MOVE {src_dir.name}/  ⇒  members/{proper_id}/  (member_name='{member_name}')")

    if not apply:
        return

    members_dir.mkdir(parents=True, exist_ok=True)
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    shutil.copytree(src_dir, dst_dir)  # copy first, verify, then remove source
    shutil.rmtree(src_dir)

    for item in list(dst_dir.iterdir()):
        if item.suffix.lower() != ".json":
            new_file = dst_dir / f"{proper_id}{item.suffix}"
            if item != new_file:
                item.rename(new_file)

    out_path = dst_dir / "output.json"
    data = _load_json(out_path) or {}
    old_ext = Path(data.get("filename", "")).suffix
    data["document_id"] = proper_id
    data["member_name"] = member_name
    data["filename"] = f"{proper_id}{old_ext}"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def cleanup_ref_no(ref_dir: Path, apply: bool) -> dict:
    ref_no = ref_dir.name
    report = [f"[{ref_no}]"]
    changes = 0

    members_dir = ref_dir / "members"
    member_docs = _scan_members_dir(members_dir)
    member_ids = {_extracted_id_number(oj) for _, oj in member_docs if _extracted_id_number(oj)}

    key_individuals = _load_json(ref_dir / "key_individuals.json") or []

    for entry in sorted(ref_dir.iterdir()):
        if not entry.is_dir() or entry.name == "members":
            continue

        name = entry.name

        # Case 1: bare root-level identity folder (EID-{ref_no} / PP-{ref_no})
        if name.startswith(IDENTITY_PREFIXES):
            oj = _load_json(entry / "output.json")
            id_num = _extracted_id_number(oj)
            ex_name = _extracted_name(oj)

            if id_num and id_num in member_ids:
                report.append(f"    → DELETE {name}/  (duplicate — same ID {id_num} already under members/)")
                changes += 1
                if apply:
                    shutil.rmtree(entry)
            elif not id_num and not ex_name:
                # No usable identity data (failed OCR / rejected upload) — don't guess
                # a member_name. Flag for manual review instead of auto-migrating.
                report.append(f"    ⚠️  SKIP {name}/  (no extracted name/ID — likely a failed/invalid upload; review manually)")
            else:
                # Not migrated yet — move it in. Try to resolve the right display_name
                # from key_individuals.json (match by name), else fall back to extracted name.
                match_ki = next(
                    (k for k in key_individuals
                     if k.get("display_name", "").strip().upper() == ex_name),
                    None
                )
                member_name = (match_ki or {}).get("display_name") or ex_name
                _move_into_members(entry, members_dir, member_name, apply, report)
                changes += 1
            continue

        # Case 2: known business-doc folder — leave alone
        if name.startswith(BUSINESS_DOC_PREFIXES):
            continue

        # Case 3: legacy per-name folder (doesn't match any known prefix)
        contents = list(entry.iterdir())
        if not contents:
            report.append(f"    → DELETE {name}/  (empty legacy folder)")
            changes += 1
            if apply:
                entry.rmdir()
        else:
            # Non-empty legacy folder — check whether its content duplicates
            # something already under members/; if so delete, else migrate.
            nested_doc_dirs = [c for c in contents if c.is_dir()]
            if not nested_doc_dirs:
                report.append(f"    ⚠️  SKIP {name}/  (non-empty, unexpected shape — inspect manually)")
                continue
            for nested in nested_doc_dirs:
                oj = _load_json(nested / "output.json")
                id_num = _extracted_id_number(oj)
                if id_num and id_num in member_ids:
                    report.append(f"    → DELETE {name}/{nested.name}/  (duplicate — same ID {id_num} already under members/)")
                    changes += 1
                    if apply:
                        shutil.rmtree(nested)
                else:
                    _move_into_members(nested, members_dir, name, apply, report)
                    changes += 1
            if apply and entry.exists() and not list(entry.iterdir()):
                entry.rmdir()

    if changes == 0:
        report.append("    ✓ nothing to fix")

    return {"ref_no": ref_no, "changes": changes, "report": report}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv

    base = get_documents_base_path()
    if not base.exists():
        print(f"❌ Documents base path not found: {base}")
        return

    ref_dirs = [base / args[0]] if args else sorted(d for d in base.iterdir() if d.is_dir())

    print("=" * 80)
    print(f"🔧 ORPHANED MEMBER FOLDER CLEANUP  —  mode: {'APPLY (writing changes)' if apply else 'DRY RUN (no changes)'}")
    print("=" * 80)
    print()

    total_changes = 0
    for ref_dir in ref_dirs:
        if not ref_dir.exists() or not ref_dir.is_dir():
            continue
        result = cleanup_ref_no(ref_dir, apply)
        for line in result["report"]:
            print(line)
        total_changes += result["changes"]

    print()
    print("=" * 80)
    print(f"📊 SUMMARY: {total_changes} change(s) {'applied' if apply else 'identified (dry run — nothing written)'}")
    print("=" * 80)
    if not apply and total_changes > 0:
        print("Re-run with --apply to perform these changes.")


if __name__ == "__main__":
    main()
