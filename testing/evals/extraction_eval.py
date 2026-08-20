"""Bounded AI extraction eval (P3) — accuracy + consistency on a SYNTHETIC deal.

Runs the REAL ClaudeExtractor against the synthetic signed-PA fixture (known
ground truth) N times and scores per-field accuracy + cross-run consistency.
Costs real Anthropic budget, so it is a standalone script (never run in CI) and
capped at a few calls. Synthetic data only — the ZDR gate stays satisfied via
SYNTHETIC_ONLY=true.

    cd backend && SYNTHETIC_ONLY=true .venv/bin/python ../testing/evals/extraction_eval.py [runs]
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
os.environ.setdefault("SYNTHETIC_ONLY", "true")

from app.ingestion.extractor import ClaudeExtractor  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[2] / "backend/tests/fixtures/synthetic_pa_signed.pdf"

# Ground truth from make_fixtures.py (the synthetic signed PA). Each entry:
# field name -> (expected, kind) where kind drives the match rule.
GROUND_TRUTH: dict[str, tuple[str, str]] = {
    "purchase_price": ("850000", "money"),
    "loan_amount": ("680000", "money"),
    "initial_deposit_amount": ("25500", "money"),
    "buyer_names": ("Alex Synthetic and Sam Synthetic", "names"),
    "seller_names": ("Pat Placeholder", "names"),
    "property_address": ("123 Stub St", "text"),
    "acceptance_date": ("2026-07-10", "date"),
    "inspection_contingency_days": ("17", "num"),
    "loan_contingency_days": ("21", "num"),
    "appraisal_contingency_days": ("17", "num"),
    "insurance_contingency_days": ("17", "num"),
    "disclosure_delivery_days": ("7", "num"),
    "escrow_holder": ("Synthetic Escrow", "text"),
    "buyer_agent": ("Casey Synthetic", "text"),
    "listing_agent": ("Riley Synthetic", "text"),
}


def _norm_money(v: str) -> str:
    m = re.search(r"[\d,]+(?:\.\d+)?", v or "")
    return str(int(float(m.group(0).replace(",", "")))) if m else ""


def _matches(expected: str, actual: str, kind: str) -> bool:
    if actual is None:
        return False
    a, e = actual.strip().lower(), expected.strip().lower()
    if kind == "money":
        return _norm_money(actual) == _norm_money(expected)
    if kind == "num":
        return re.sub(r"\D", "", actual) == re.sub(r"\D", "", expected) != ""
    if kind == "date":
        return expected in actual or actual in expected
    if kind == "names":
        # Separator-agnostic: "A and B" == "A, B". Compare the person sets.
        split = lambda s: {p.strip() for p in re.split(r"\s*(?:,| and | & |;|/)\s*", s) if p.strip()}
        return split(e) == split(a)
    # text: every significant token of the expected appears in the actual
    return all(tok in a for tok in e.split() if len(tok) > 2)


def run_once(extractor: ClaudeExtractor) -> dict[str, str]:
    result = extractor.extract(pdf_bytes=FIXTURE.read_bytes(), doc_type="purchase_agreement")
    values = {f.name: f.value for f in result.fields}
    values["__doc_looks_like__"] = result.doc_looks_like
    values["__signature_detected__"] = str(result.signature_detected)
    return values


def main() -> None:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    print(f"Extraction eval — {runs} run(s) on {FIXTURE.name} (model={os.environ.get('EXTRACTION_MODEL', 'claude-sonnet-5')})\n")
    extractor = ClaudeExtractor()
    outputs = [run_once(extractor) for _ in range(runs)]

    print("## Accuracy (run 1 vs ground truth)")
    first = outputs[0]
    correct = 0
    for name, (expected, kind) in GROUND_TRUTH.items():
        got = first.get(name)
        ok = _matches(expected, got or "", kind)
        correct += ok
        print(f"  [{'OK ' if ok else 'MISS'}] {name}: expected~{expected!r} got={got!r}")
    print(f"  → {correct}/{len(GROUND_TRUTH)} fields correct")
    print(f"  doc_looks_like={first.get('__doc_looks_like__')} (expect purchase_agreement)")
    print(f"  signature_detected={first.get('__signature_detected__')} (expect True)")

    if runs > 1:
        print("\n## Consistency (field agreement across runs)")
        names = set().union(*[set(o) for o in outputs])
        stable = 0
        for name in sorted(names):
            vals = {(_norm_money(o.get(name, "")) if name in GROUND_TRUTH and GROUND_TRUTH[name][1] == "money" else (o.get(name) or "")) for o in outputs}
            agree = len(vals) == 1
            stable += agree
            if not agree:
                print(f"  [VARY] {name}: {[o.get(name) for o in outputs]}")
        print(f"  → {stable}/{len(names)} fields identical across all {runs} runs")


if __name__ == "__main__":
    main()
