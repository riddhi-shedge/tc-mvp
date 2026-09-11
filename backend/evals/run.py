"""Extraction regression evals — real PDFs, real model, labeled ground truth.

The unit suite (pytest) proves the plumbing with a fake extractor; THIS suite
proves the model+prompt stack still reads real documents correctly. Labels in
golden.json come from audit-verified deal facts. Deliberately NOT part of
pytest: each case is a paid model call on a real document, so it runs when
invoked — after prompt/schema/model changes, and as part of the audit ritual.

Run:  cd backend && PYTHONPATH=. .venv/bin/python evals/run.py [case-name-filter]
Exit: 0 all pass, 1 any fail (regression!), 2 harness/environment error.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

import os  # noqa: E402

from supabase import create_client  # noqa: E402

from app.ingestion.extractor import ExtractionBlocked, ExtractionFailed  # noqa: E402
from app.ingestion.precheck import decrypt_pdf  # noqa: E402
from app.ingestion.routes import get_extractor, get_inbox_repo  # noqa: E402

GOLDEN = json.loads((Path(__file__).parent / "golden.json").read_text())


def resolve_pdfs(names: list[str]) -> dict[str, bytes]:
    """attachment_name -> decrypted bytes, via the newest inbox row per name."""
    db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    rows = (
        db.table("ingestion_inbox")
        .select("attachment_name, storage_path, created_at")
        .in_("attachment_name", names)
        .order("created_at", desc=True)
        .execute()
        .data
    )
    inbox = get_inbox_repo()
    out: dict[str, bytes] = {}
    for r in rows:
        n = r["attachment_name"]
        if n in out or not r.get("storage_path"):
            continue
        readable = decrypt_pdf(inbox.download_attachment(r["storage_path"]))
        if readable is not None:
            out[n] = readable
    return out


def run_case(case: dict, pdf: bytes, extractor) -> list[str]:
    """Empty list = pass; else the failure reasons."""
    fails: list[str] = []
    if case["kind"] == "extract":
        result = extractor.extract(pdf_bytes=pdf, doc_type=case["doc_type"])
        values = {f.name: f.value for f in result.fields}
        for field, pattern in case["expect_fields"].items():
            got = values.get(field)
            if got is None:
                fails.append(f"{field}: MISSING (expected /{pattern}/)")
            elif not re.search(pattern, got, re.IGNORECASE):
                fails.append(f"{field}: {got!r} !~ /{pattern}/")
    elif case["kind"] == "classify":
        result = extractor.extract(pdf_bytes=pdf, doc_type="other")
        if result.doc_looks_like not in case["expect_type"]:
            fails.append(f"classified {result.doc_looks_like!r}, expected {case['expect_type']}")
    elif case["kind"] == "facts":
        facts = extractor.extract_facts(pdf_bytes=pdf)
        haystack = f"{facts.doc_kind} {facts.summary}"
        if not re.search(case["expect_match"], haystack, re.IGNORECASE):
            fails.append(f"kind/summary {haystack[:120]!r} !~ /{case['expect_match']}/")
        if not facts.facts:
            fails.append("universal read returned zero facts")
    else:
        fails.append(f"unknown case kind {case['kind']!r}")
    return fails


def main() -> int:
    name_filter = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    cases = [c for c in GOLDEN["cases"] if name_filter in c["name"].lower()]
    if not cases:
        print(f"no cases match {name_filter!r}")
        return 2
    try:
        pdfs = resolve_pdfs([c["attachment_name"] for c in cases])
    except Exception as exc:  # noqa: BLE001
        print(f"HARNESS ERROR resolving PDFs: {type(exc).__name__}: {exc}")
        return 2
    extractor = get_extractor()
    passed = failed = skipped = 0
    for case in cases:
        pdf = pdfs.get(case["attachment_name"])
        if pdf is None:
            print(f"SKIP  {case['name']} — PDF not found in storage")
            skipped += 1
            continue
        try:
            fails = run_case(case, pdf, extractor)
        except (ExtractionFailed, ExtractionBlocked) as exc:
            fails = [f"extraction error: {exc}"]
        if fails:
            failed += 1
            print(f"FAIL  {case['name']}")
            for f in fails:
                print(f"      - {f}")
        else:
            passed += 1
            print(f"pass  {case['name']}")
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped / {len(cases)} cases")
    if failed:
        print("A failure here means the model+prompt stack regressed on a REAL document.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
