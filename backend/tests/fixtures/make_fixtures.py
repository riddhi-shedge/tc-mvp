"""Generate the SYNTHETIC PDF fixtures (dev-only; requires reportlab).

Every document is plainly labeled SYNTHETIC and uses a plain layout that is
deliberately NOT the C.A.R. form (Rule 1: no blank/pre-filled C.A.R. forms in
the repo, ever). No real names, addresses, SSNs, or bank details (Rule 5).

Run from backend/:  .venv/bin/python tests/fixtures/make_fixtures.py
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent

PA_PAGE_1 = [
    "SYNTHETIC RESIDENTIAL PURCHASE AGREEMENT (TEST FIXTURE)",
    "This is a synthetic document for software testing. Not a C.A.R. form.",
    "",
    "Buyers: Alex Synthetic and Sam Synthetic",
    "Sellers: Pat Placeholder",
    "Property: 123 Stub St, Sacramento, CA 95814",
    "APN: 000-000-000",
    "",
    "Purchase price: $850,000",
    "Initial deposit: $25,500 due within 3 business days after acceptance",
    "Loan amount: $680,000 (conventional financing)",
    "Down payment: $144,500",
    "All cash: No",
    "",
    "Close of escrow: 30 days after acceptance",
    "Possession: at close of escrow, 6:00 PM",
]

PA_PAGE_2 = [
    "SYNTHETIC PURCHASE AGREEMENT — PAGE 2 (TEST FIXTURE)",
    "",
    "Contingency periods (days after acceptance):",
    "  Investigation/inspection contingency: 17 days",
    "  Loan contingency: 21 days",
    "  Appraisal contingency: 17 days",
    "  Insurance contingency: 17 days",
    "  Seller disclosure delivery: 7 days",
    "  Verification of down payment and closing costs: 3 days",
    "",
    "Buyer's agent: Casey Synthetic, Example Realty (synthetic)",
    "Listing agent: Riley Synthetic, Placeholder Homes (synthetic)",
    "Escrow holder: Synthetic Escrow Co., escrow #SYN-0001",
    "",
    "Confirmation of acceptance: 2026-07-10",
    "",
    "SIGNED: /s/ Alex Synthetic    Date: 2026-07-10",
    "SIGNED: /s/ Sam Synthetic     Date: 2026-07-10",
    "SIGNED: /s/ Pat Placeholder   Date: 2026-07-10",
]

POF_PAGE = [
    "SYNTHETIC PROOF OF FUNDS (TEST FIXTURE)",
    "This is a synthetic document for software testing.",
    "Account holder: Alex Synthetic",
    "Available funds: $200,000 (synthetic)",
    "No account numbers are shown on this synthetic document.",
]


def _write(path: Path, pages: list[list[str]], *, draw_text: bool = True) -> None:
    c = canvas.Canvas(str(path), pagesize=LETTER)
    for lines in pages:
        if draw_text:
            y = 750
            c.setFont("Helvetica", 11)
            for line in lines:
                c.drawString(72, y, line)
                y -= 18
        else:
            # Image-only "scan": a rectangle, no text layer at all.
            c.rect(72, 300, 450, 300, fill=0)
        c.showPage()
    c.save()
    print(f"wrote {path.name}")


if __name__ == "__main__":
    _write(OUT / "synthetic_pa_signed.pdf", [PA_PAGE_1, PA_PAGE_2])
    unsigned_p2 = [line for line in PA_PAGE_2 if not line.startswith("SIGNED")]
    _write(OUT / "synthetic_pa_unsigned.pdf", [PA_PAGE_1, unsigned_p2])
    _write(OUT / "synthetic_pa_truncated.pdf", [PA_PAGE_1])  # 1 page: "missing pages"
    _write(OUT / "synthetic_scan_no_text.pdf", [[], []], draw_text=False)
    _write(OUT / "synthetic_pof.pdf", [POF_PAGE])
