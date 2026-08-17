"""Automated logic probes (P1) — reproduce the Part-3 hotspots deterministically.

No API cost: uses InMemoryRepo + the pure functions. Each check asserts the
CORRECT/desired behavior; a FAIL is a candidate confirmed bug. Run:

    cd backend && PYTHONPATH=. .venv/bin/python ../testing/probes/logic_probes.py
"""

from __future__ import annotations

from app.compliance.timeline import _parse_date
from app.contracts.payload import CounterMeta, ExtractedField, Payload
from app.ingestion.detector import detect_doc_type
from app.master.parties import party_key
from app.master.repo import _addr_core, _parse_loose_date, _parse_money
from tests.fake_repo import InMemoryRepo

FAILS: list[str] = []
PASSES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASSES if ok else FAILS).append(f"{name}: {detail}")
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")


def _price(v: str, confirmed: bool = True) -> ExtractedField:
    return ExtractedField(name="purchase_price", value=v, confidence=1.0, confirmed=confirmed)


def _eff_price(repo: InMemoryRepo, tid: str) -> str | None:
    return (repo.get_full_state(tid)["effective_fields"].get("purchase_price") or {}).get("value")


print("\n### HOTSPOT 1 — re-uploading the PA must not revert a counter ###")
repo = InMemoryRepo()
tid = repo.create_transaction(property_address="1 Probe St", actor="tc")["id"]
repo.write_payload(transaction_id=tid, payload=Payload(document_id="pa", transaction_id=tid, extracted_fields=[_price("$1,800,000")], document_type="purchase_agreement"), actor="tc")
repo.write_payload(transaction_id=tid, payload=Payload(document_id="sco", transaction_id=tid, extracted_fields=[_price("$1,900,000")], document_type="seller_counter_offer", counter_meta=CounterMeta(recipient_signed=True)), actor="tc")
check("counter supersedes PA (baseline)", _eff_price(repo, tid) == "$1,900,000", f"effective={_eff_price(repo, tid)}")
# Now re-upload / correct the PA (a later created_at).
repo.write_payload(transaction_id=tid, payload=Payload(document_id="pa2", transaction_id=tid, extracted_fields=[_price("$1,800,000")], document_type="purchase_agreement"), actor="tc")
check("counter survives a PA re-upload", _eff_price(repo, tid) == "$1,900,000", f"effective={_eff_price(repo, tid)} (expected $1,900,000)")

print("\n### HOTSPOT 2 — an UNCONFIRMED counter must not supersede ###")
repo2 = InMemoryRepo()
t2 = repo2.create_transaction(property_address="2 Probe St", actor="tc")["id"]
repo2.write_payload(transaction_id=t2, payload=Payload(document_id="pa", transaction_id=t2, extracted_fields=[_price("$1,800,000")], document_type="purchase_agreement"), actor="tc")
repo2.write_payload(transaction_id=t2, payload=Payload(document_id="sco", transaction_id=t2, extracted_fields=[_price("$1,900,000", confirmed=False)], document_type="seller_counter_offer"), actor="tc")
check("unconfirmed counter does not win", _eff_price(repo2, t2) == "$1,800,000", f"effective={_eff_price(repo2, t2)}")

print("\n### HOTSPOT 5 — date parsing robustness ###")
for raw, expect_desc in [
    ("01/02/2025", "US MM/DD (Jan 2) — assumption to document"),
    ("13/01/2025", "invalid MM/DD; should NOT silently misparse"),
    ("March 2025", "month+year, no day"),
    ("TBD", "non-date"),
    ("2025-08-04", "ISO"),
    ("8/4/25", "2-digit year"),
]:
    d = _parse_date(raw)
    print(f"  _parse_date({raw!r}) -> {d}   ({expect_desc})")
check("13/01/2025 not misparsed to a valid date", _parse_date("13/01/2025") is None, f"got {_parse_date('13/01/2025')}")
check("'March 2025' (no day) -> None (not day=today)", _parse_date("March 2025") is None, f"got {_parse_date('March 2025')}")

print("\n### HOTSPOT (money) — preapproval/loan amount parsing ###")
for raw in ["$1,100,000.00 (61.11% of purchase price)", "$1.8M", "$900k", "$2,600,000", "1,900,000"]:
    print(f"  _parse_money({raw!r}) -> {_parse_money(raw)}")
check("'$1.8M' parses to 1,800,000 (not 1.8)", _parse_money("$1.8M") == 1_800_000, f"got {_parse_money('$1.8M')}")
check("'$900k' parses to 900,000 (not 900)", _parse_money("$900k") == 900_000, f"got {_parse_money('$900k')}")

print("\n### HOTSPOT 7 — detector edge cases ###")
for fn, expect in [
    ("counteroffer.pdf", "counter_offer"),
    ("encounter_notes.pdf", "unknown"),
    ("Seller Counter 1.pdf", "seller_counter_offer"),
    ("PRELIMINARY REPORT and property inspection.pdf", "preliminary_report/property_inspection?"),
    ("proof of funds - preapproval.pdf", "preapproval? proof_of_funds?"),
]:
    print(f"  detect_doc_type({fn!r}) -> {detect_doc_type(fn, None)}   (note: {expect})")
check("'encounter_notes' is not a counter offer", detect_doc_type("encounter_notes.pdf", None) != "counter_offer", f"got {detect_doc_type('encounter_notes.pdf', None)}")

print("\n### HOTSPOT 8 — party dedup across spelling variants ###")
a = party_key("lender", "Belana A Chechelnitsky")
b = party_key("lender", "Belana A. Chechelnitsky")
c = party_key("lender", "Belana Chechelnitsky")
print(f"  keys: {a} | {b} | {c}")
check("'Belana A' vs 'Belana A.' dedupe equal", a == b, f"{a} vs {b}")

print("\n### HOTSPOT (address) — inspection address match with unit prefix ###")
core1 = _addr_core("Unit 5, 21989 McClellan Rd")
core2 = _addr_core("21989 McClellan Road, Cupertino")
print(f"  _addr_core('Unit 5, 21989 McClellan Rd') = {core1!r}")
print(f"  _addr_core('21989 McClellan Road, Cupertino') = {core2!r}")
check("unit-prefixed address still matches property", core1 == core2 or core2 in core1 or core1 in core2, f"{core1!r} vs {core2!r}")

print("\n" + "=" * 70)
print(f"RESULT: {len(PASSES)} pass, {len(FAILS)} FAIL")
for f in FAILS:
    print(f"  ✗ {f}")
