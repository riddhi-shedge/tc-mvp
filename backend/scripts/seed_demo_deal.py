"""The golden demo deal: one command seeds (or resets) a complete synthetic CA
transaction so a live pitch never depends on whatever data is in the DB.

    cd backend && PYTHONPATH=. .venv/bin/python scripts/seed_demo_deal.py

What it builds, in the demo org:
  * a purchase agreement filed with evidence-backed §5 fields (one low-
    confidence non-deadline field left unconfirmed for the "verify" beat)
  * derived parties and tasks, all deadline-driving fields confirmed
  * a REAL compliance run (verified CA ruleset, in-process) → deadlines,
    tasks, risk flags — dates land mid-contingency relative to today
  * a seller counter offer whose price supersedes the PA's on every rollup
  * a repair item, ops lanes in motion, an NBP served on the lapsed deposit
    deadline, a co-pilot draft awaiting Approve & Send, and a deal note

Idempotent: re-running deletes the previous demo deal (matched by its marker
address) and rebuilds with fresh dates. Synthetic data only — every name,
address, and number below is invented. Rule 2 intact: no wiring/account data.
"""

from __future__ import annotations

import base64
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

from app.common import orgs  # noqa: E402
from app.common.dates import ca_today  # noqa: E402
from app.compliance.ca_rules import load_verified_ruleset  # noqa: E402
from app.compliance.service import run_for_transaction  # noqa: E402
from app.contracts.compliance import DealState  # noqa: E402
from app.contracts.payload import ExtractedField, Payload  # noqa: E402
from app.compliance.master_client import _state_from_slice  # noqa: E402
from app.ingestion.inbox_repo import SupabaseInboxRepo  # noqa: E402
from app.master.repo import SupabaseRepo  # noqa: E402

ACTOR = "seed:demo"
DEMO_ADDRESS = "4285 Alder Creek Way, Sacramento, CA 95833"
PDF_FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "synthetic_pa_signed.pdf"


class SeedComplianceClient:
    """In-process stand-in for HttpComplianceMasterClient: same slice the
    /compliance-state route serves, same apply the /compliance-result route
    runs — without needing a running API or its service token."""

    def __init__(self, repo: SupabaseRepo) -> None:
        self._repo = repo

    def read_deal_state(self, transaction_id: str) -> DealState | None:
        state = self._repo.get_full_state(transaction_id)
        if state is None:
            return None
        slice_ = {
            "transaction_id": transaction_id,
            "fields": [
                {
                    "name": name,
                    "value": d["value"],
                    "confirmed": d["confirmed"],
                    "deadline_driving": d["deadline_driving"],
                }
                for name, d in state.get("effective_fields", {}).items()
            ],
            "parties": [
                {"role": p.get("role", ""), "name": p.get("name"), "email": p.get("email")}
                for p in state.get("parties", [])
            ],
            "documents": [
                {"doc_type": d.get("doc_type"), "status": d.get("status", "")}
                for d in state.get("documents", [])
            ],
            "tasks": [
                {"title": t.get("title", ""), "status": t.get("status", "")}
                for t in state.get("tasks", [])
            ],
        }
        return _state_from_slice(slice_)

    def write_compliance_result(self, result: Any) -> None:
        self._repo.apply_compliance_result(result=result, actor="compliance-service")


def _pa_fields(acceptance: str) -> list[ExtractedField]:
    f = ExtractedField
    return [
        f(name="buyer_names", value="Priya Natarajan and Dev Natarajan", confidence=0.97,
          evidence="BUYER: Priya Natarajan and Dev Natarajan ('Buyer')"),
        f(name="seller_names", value="Margaret Ellison", confidence=0.96,
          evidence="SELLER: Margaret Ellison ('Seller')"),
        f(name="property_address", value=DEMO_ADDRESS, confidence=0.98,
          evidence="the real property described as 4285 Alder Creek Way, Sacramento, CA 95833"),
        f(name="apn", value="277-0413-021", confidence=0.55,
          evidence="Assessor's Parcel No. 277-O413-O21"),  # low: OCR-ambiguous 0/O
        f(name="purchase_price", value="$912,000", confidence=0.98,
          evidence="The purchase price offered for the Property is $912,000"),
        f(name="initial_deposit_amount", value="$27,360", confidence=0.95,
          evidence="INITIAL DEPOSIT: Buyer shall deliver deposit ... $27,360"),
        f(name="loan_amount", value="$729,600", confidence=0.94,
          evidence="FIRST LOAN in the amount of ... $729,600"),
        f(name="down_payment", value="$182,400", confidence=0.93,
          evidence="BALANCE OF DOWN PAYMENT ... $182,400"),
        f(name="financing_type", value="conventional", confidence=0.92,
          evidence="conventional or other financing"),
        f(name="all_cash", value="false", confidence=0.95,
          evidence="This is NOT an all cash offer"),
        f(name="acceptance_date", value=acceptance, confidence=0.90,
          evidence=f"Acceptance was personally received by Buyer's authorized agent on {acceptance}"),
        f(name="close_of_escrow", value="45 days after acceptance", confidence=0.91,
          evidence="Close of Escrow shall occur 45 Days after Acceptance"),
        f(name="possession_date", value="at close of escrow, 6:00 PM", confidence=0.90,
          evidence="Seller shall deliver possession ... at 6 PM on the date of Close Of Escrow"),
        f(name="emd_due_days", value="3 business days", confidence=0.90,
          evidence="deposit shall be delivered ... within 3 business days after Acceptance"),
        f(name="inspection_contingency_days", value="17", confidence=0.93,
          evidence="remove the applicable contingency ... within 17 Days After Acceptance"),
        f(name="loan_contingency_days", value="21", confidence=0.92,
          evidence="loan contingency shall remain in effect for 21 Days After Acceptance"),
        f(name="appraisal_contingency_days", value="17", confidence=0.92,
          evidence="appraisal contingency ... 17 Days After Acceptance"),
        f(name="insurance_contingency_days", value="17", confidence=0.88,
          evidence="insurance ... 17 Days After Acceptance"),
        f(name="disclosure_delivery_days", value="7", confidence=0.93,
          evidence="Seller shall deliver to Buyer all Reports ... within 7 Days After Acceptance"),
        f(name="verification_of_funds_days", value="3", confidence=0.90,
          evidence="verification of down payment and closing costs ... 3 Days After Acceptance"),
        f(name="loan_contingency_present", value="true", confidence=0.94,
          evidence="This Agreement is contingent upon Buyer obtaining the loan"),
        f(name="appraisal_contingency_present", value="true", confidence=0.94,
          evidence="contingent upon a written appraisal"),
        f(name="inspection_contingency_present", value="true", confidence=0.94,
          evidence="Buyer's right to inspect the Property"),
        f(name="insurance_contingency_present", value="true", confidence=0.85,
          evidence="ability to obtain homeowner's insurance"),
        f(name="buyer_agent", value="Hector Ramirez, Rivera & Co. Realty", confidence=0.95,
          evidence="Buyer's Brokerage Firm: Rivera & Co. Realty ... Hector Ramirez"),
        f(name="listing_agent", value="June Park, Meridian Homes", confidence=0.95,
          evidence="Seller's Brokerage Firm: Meridian Homes ... June Park"),
        f(name="escrow_holder", value="Golden Gate Escrow (Lena Ortiz)", confidence=0.93,
          evidence="Escrow Holder: Golden Gate Escrow"),
        f(name="title_company", value="North Coast Title", confidence=0.92,
          evidence="title insurance ... issued by North Coast Title"),
        f(name="lender_contact", value="Marcus Webb, Pacific Crest Lending", confidence=0.91,
          evidence="Buyer's lender: Pacific Crest Lending, Marcus Webb"),
        f(name="items_included", value="refrigerator, washer, dryer", confidence=0.89,
          evidence="ADDITIONAL ITEMS INCLUDED: refrigerator, washer, dryer"),
    ]


def main() -> int:
    repo = SupabaseRepo()
    inbox = SupabaseInboxRepo()
    org_id = orgs.DEMO_ORG_ID
    try:
        from app.master.org_repo import SupabaseOrgsRepo

        if SupabaseOrgsRepo().org_info(org_id) is None:
            print(f"seed: demo org {org_id} not found (is migration 26 applied?)")
            return 1
    except Exception as exc:
        print(f"seed: cannot reach the database ({type(exc).__name__})")
        return 1

    # ---- Reset: remove any previous demo deal (matched by marker address) ----
    for t in repo.list_transactions(org_id=org_id):
        if t.get("property_address") == DEMO_ADDRESS:
            repo.delete_transaction(transaction_id=t["id"], actor=ACTOR)
            print(f"seed: removed previous demo deal {t['id'][:8]}")

    today = ca_today()
    acceptance = (today - timedelta(days=10)).isoformat()

    # ---- Store the synthetic PA PDF so ledger previews work ----
    pdf_b64 = base64.standard_b64encode(PDF_FIXTURE.read_bytes()).decode()
    storage_path = inbox.store_attachment(
        source="manual", filename="RPA-signed-alder-creek.pdf", content_base64=pdf_b64
    )

    # ---- The deal + the PA filing (mirrors the HITL confirm flow) ----
    txn = repo.create_transaction(property_address=DEMO_ADDRESS, actor=ACTOR, org_id=org_id)
    tid = txn["id"]
    print(f"seed: created demo deal {tid}")

    repo.write_payload(
        transaction_id=tid,
        payload=Payload(
            document_id="seed-pa-1",
            transaction_id=tid,
            document_type="purchase_agreement",
            document_storage_ref=storage_path,
            extracted_fields=_pa_fields(acceptance),
        ),
        actor=ACTOR,
    )
    repo.derive_parties_from_fields(transaction_id=tid, actor=ACTOR)
    repo.derive_tasks_from_fields(transaction_id=tid, actor=ACTOR)

    # Confirm everything EXCEPT the deliberately low-confidence APN — the demo's
    # "Terra is honest when unsure; you verify" beat, without blocking the gate.
    state = repo.get_full_state(tid) or {}
    to_confirm = [
        fld["id"] for fld in state.get("extracted_fields", [])
        if not fld["confirmed"] and fld["name"] != "apn"
    ]
    repo.confirm_fields(transaction_id=tid, field_ids=to_confirm, actor=ACTOR)

    # ---- Real compliance run: the verified CA ruleset computes the timeline ----
    client = SeedComplianceClient(repo)
    result = run_for_transaction(tid, client, as_of=today, rules=load_verified_ruleset())
    print(f"seed: timeline built ({len(result.deadlines)} deadlines, "
          f"{len(result.risk_flags)} risk flags)")

    # ---- Seller counter: price supersedes the PA's everywhere ----
    repo.write_payload(
        transaction_id=tid,
        payload=Payload(
            document_id="seed-sco-1",
            transaction_id=tid,
            document_type="seller_counter_offer",
            document_storage_ref=storage_path,
            document_label="Seller Counter Offer No. 1",
            extracted_fields=[
                ExtractedField(
                    name="purchase_price", value="$925,000", confidence=0.97, confirmed=True,
                    evidence="Price to be $925,000 (Nine Hundred Twenty-Five Thousand Dollars)",
                ),
            ],
        ),
        actor=ACTOR,
    )

    # ---- Deal texture: repair, ops lanes, NBP, draft, note, stage ----
    repo.create_repair(
        transaction_id=tid,
        description="Section 1 termite items per inspection report; seller credit at close",
        source_document_id=None,
        actor=ACTOR,
    )
    repo.advance_ops_item(transaction_id=tid, lane="nhd", status="ordered",
                          occurred_on=(today - timedelta(days=6)).isoformat(),
                          note=None, actor=ACTOR)
    repo.advance_ops_item(transaction_id=tid, lane="nhd", status="done",
                          occurred_on=(today - timedelta(days=1)).isoformat(),
                          note="Report delivered to all parties", actor=ACTOR)
    repo.advance_ops_item(transaction_id=tid, lane="warranty", status="ordered",
                          occurred_on=(today - timedelta(days=4)).isoformat(),
                          note=None, actor=ACTOR)

    # NBP on the (lapsed) deposit deadline, if the ruleset produced one.
    state = repo.get_full_state(tid) or {}
    emd = next(
        (d for d in state.get("deadlines", [])
         if "deposit" in (d.get("name") or "").lower() or "emd" in (d.get("name") or "").lower()),
        None,
    )
    if emd is not None:
        try:
            repo.create_notice(
                transaction_id=tid, deadline_id=emd["id"], kind="nbp",
                served_date=today.isoformat(),
                cure_expires=(today + timedelta(days=2)).isoformat(),
                actor=ACTOR,
            )
            print("seed: NBP served on the deposit deadline")
        except Exception as exc:  # flavor only — never fail the seed over it
            print(f"seed: skipped NBP ({type(exc).__name__})")

    lender = repo.lender_party(tid)
    repo.create_message(
        transaction_id=tid,
        subject="Loan status ahead of the contingency deadline",
        body=(
            "Hi Marcus,\n\nChecking in on the Natarajan loan for 4285 Alder Creek Way. "
            "The loan contingency comes up soon and we'd like to stay ahead of it. "
            "Could you share where the file stands (appraisal ordered, underwriting, "
            "any conditions outstanding)?\n\nThank you!"
        ),
        party_id=(lender or {}).get("id"),
        actor=ACTOR,
        action="message.drafted",
        details={
            "purpose": "lender_status",
            "why": "Loan contingency deadline is approaching and no lender status is on file.",
            "ai": True,
        },
    )
    repo.add_deal_note(
        transaction_id=tid,
        body="Seller prefers a Thursday close. Confirm timing with escrow before scheduling signing.",
        color="y",
        actor=ACTOR,
    )
    repo.set_transaction_stage(transaction_id=tid, stage="cont", actor=ACTOR)

    fresh = repo.get_full_state(tid) or {}
    print(
        "seed: done. "
        f"fields={len(fresh.get('extracted_fields', []))} "
        f"parties={len(fresh.get('parties', []))} "
        f"deadlines={len(fresh.get('deadlines', []))} "
        f"tasks={len(fresh.get('tasks', []))} "
        f"docs={len(fresh.get('documents', []))} "
        f"drafts={sum(1 for m in fresh.get('messages', []) if m.get('status') == 'draft')}"
    )
    print(f"seed: open the deal at /  ->  {DEMO_ADDRESS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
