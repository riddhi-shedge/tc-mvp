"""Generate Terra's pitch assets as PDFs: the investor one-pager (letter,
portrait) and the pitch deck (16:9 landscape). Pure reportlab so the assets
regenerate in seconds when the story changes.

    cd tc-mvp && backend/.venv/bin/python docs/pitch/build_pitch_assets.py <outdir>

Sources for every market figure: docs/road-to-market.md (researched 2026-09).
No fabricated traction: status claims describe the shipped product only.
"""

from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# ---- Terra identity ----------------------------------------------------------
PINE = colors.HexColor("#123528")
PINE_DEEP = colors.HexColor("#0c261e")
SAGE = colors.HexColor("#7fa38e")
SAND = colors.HexColor("#d8b46a")
CREAM = colors.HexColor("#f1ecdd")
INK = colors.HexColor("#1d2420")
MUTED = colors.HexColor("#5f6f66")
PAPER = colors.HexColor("#faf8f2")

SERIF_B = "Times-Bold"
SANS = "Helvetica"
SANS_B = "Helvetica-Bold"

DECK_W, DECK_H = 13.333 * 72, 7.5 * 72  # 16:9


def wrap(c, text, x, y, width, font=SANS, size=10, leading=None, color=INK, max_lines=None):
    """Simple word-wrap; returns the y AFTER the last line drawn."""
    leading = leading or size * 1.42
    c.setFont(font, size)
    c.setFillColor(color)
    words = text.split()
    line = ""
    lines = []
    for w in words:
        trial = f"{line} {w}".strip()
        if c.stringWidth(trial, font, size) <= width:
            line = trial
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    if max_lines:
        lines = lines[:max_lines]
    for ln in lines:
        c.drawString(x, y, ln)
        y -= leading
    return y


def contour(c, cx, cy, r0, n, color, alpha_step=0.09):
    """The topo-loop brand motif, simplified for print."""
    import math

    for i in range(n):
        r = r0 + i * 26
        c.setStrokeColor(color)
        c.setLineWidth(0.8)
        path = c.beginPath()
        steps = 40
        for s in range(steps + 1):
            a = (s / steps) * 2 * math.pi
            wob = 1 + 0.08 * math.sin(a * 3 + i * 1.7) + 0.04 * math.sin(a * 5 + i)
            px = cx + math.cos(a) * r * wob
            py = cy + math.sin(a) * r * wob * 0.78
            if s == 0:
                path.moveTo(px, py)
            else:
                path.lineTo(px, py)
        path.close()
        c.setStrokeAlpha(max(0.08, 0.5 - i * alpha_step))
        c.drawPath(path, stroke=1, fill=0)
    c.setStrokeAlpha(1)


# ==============================================================================
# One-pager
# ==============================================================================

def build_one_pager(out: Path) -> None:
    W, H = letter
    c = canvas.Canvas(str(out), pagesize=letter)
    c.setTitle("Terra One-Pager")
    c.setAuthor("Terra")

    # Header band
    c.setFillColor(PINE)
    c.rect(0, H - 118, W, 118, stroke=0, fill=1)
    contour(c, W - 80, H - 40, 30, 4, SAND)
    c.setFillColor(CREAM)
    c.setFont(SERIF_B, 30)
    c.drawString(54, H - 62, "Terra")
    c.setFillColor(colors.HexColor("#cfe0d5"))
    c.setFont(SANS, 11.5)
    c.drawString(54, H - 84, "AI transaction coordination for California residential real estate")
    c.setFont(SANS, 8.5)
    c.setFillColor(SAND)
    c.drawString(54, H - 102, "Riddhi Shedge  ·  riddh1.shedg6@gmail.com  ·  terra-frontend-ujk2.onrender.com")

    y = H - 152
    LX, COLW = 54, W - 108

    def h(t, yy):
        c.setFillColor(PINE)
        c.setFont(SERIF_B, 13.5)
        c.drawString(LX, yy, t)
        return yy - 17

    y = h("The problem", y)
    y = wrap(c, "Every California home sale runs on a transaction coordinator: 40+ documents, "
                "a dozen statutory deadlines computed from the contract's own terms, and real "
                "liability when one slips. TCs charge $350-450 per file and manage it all with "
                "checklists, calendars, and rereading PDFs at midnight. Existing software "
                "(Open To Close, SkySlope, ListedKit) tracks tasks; none of it reads the "
                "documents or computes the obligations.", LX, y, COLW, size=9.6)
    y -= 10

    y = h("What Terra does", y)
    y = wrap(c, "Terra reads every document in the deal and shows the exact quote behind every "
                "extracted term. It computes each deadline from the contract under the current "
                "CA purchase agreement rules, recomputes when a counter changes the terms, "
                "drafts the chases and status updates, and sends nothing without a human's "
                "explicit approval. Buyers, sellers, agents, escrow, and lenders each get a "
                "scoped live view from one link, including a wire-fraud interstitial before "
                "any deposit step.", LX, y, COLW, size=9.6)
    y -= 10

    y = h("Built like the liability is real", y)
    for line in [
        "Evidence, not vibes: every value carries its verbatim source quote; low-confidence reads are flagged, never guessed.",
        "Nothing auto-sends: one approval loop for every outbound message, with per-workspace recipient allowlists.",
        "Money is unrepresentable: wiring and account data cannot be stored, by schema.",
        "Human confirms every extracted term before it drives a deadline; append-only audit log enforced by the database.",
    ]:
        c.setFillColor(SAND)
        c.setFont(SANS_B, 9)
        c.drawString(LX, y, "▸")
        y = wrap(c, line, LX + 14, y, COLW - 14, size=9.4)
        y -= 2
    y -= 8

    y = h("Market", y)
    y = wrap(c, "California is roughly one in eight US residential transactions. TCs spend "
                "$30-100/month on software today and earn $350-450 per file; Terra prices per "
                "file, where the value lands. The wedge is the state with the hardest deadline "
                "law; the ruleset is swappable by design for state two.", LX, y, COLW, size=9.6)
    y -= 10

    y = h("Status", y)
    y = wrap(c, "Live and deployed: multi-tenant workspaces with teammate invites, mandatory "
                "MFA, tenancy verified by a route-table attack test in CI, 579 backend tests, "
                "and extraction evals on real recorded documents. Demo environment runs "
                "synthetic data pending the zero-data-retention agreement. Now recruiting "
                "3-5 California TCs as design partners.", LX, y, COLW, size=9.6)
    y -= 10

    y = h("The ask", y)
    y = wrap(c, "Introductions to working California TCs and brokerage operators for pilots, "
                "and early conversations ahead of a pre-seed round.", LX, y, COLW, size=9.6)

    # Footer
    c.setFillColor(MUTED)
    c.setFont(SANS, 7.5)
    c.drawString(LX, 40, "Terra · September 2026 · Confidential")
    c.showPage()
    c.save()


# ==============================================================================
# Deck
# ==============================================================================

class Deck:
    def __init__(self, out: Path):
        self.c = canvas.Canvas(str(out), pagesize=(DECK_W, DECK_H))
        self.c.setTitle("Terra Pitch Deck")
        self.c.setAuthor("Terra")
        self.n = 0

    def _chrome(self, dark=False):
        c = self.c
        c.setFillColor(PINE if dark else PAPER)
        c.rect(0, 0, DECK_W, DECK_H, stroke=0, fill=1)
        self.n += 1
        c.setFont(SANS, 8)
        c.setFillColor(SAND if dark else MUTED)
        c.drawString(48, 26, "Terra")
        c.drawRightString(DECK_W - 48, 26, f"{self.n:02d}")

    def title_slide(self):
        c = self.c
        self._chrome(dark=True)
        contour(c, DECK_W - 200, DECK_H / 2, 60, 6, SAND)
        c.setFillColor(CREAM)
        c.setFont(SERIF_B, 64)
        c.drawString(70, DECK_H / 2 + 40, "Terra")
        c.setFont(SERIF_B, 21)
        c.setFillColor(colors.HexColor("#cfe0d5"))
        c.drawString(72, DECK_H / 2 - 4, "The AI transaction coordinator that shows its work.")
        c.setFont(SANS, 12)
        c.setFillColor(SAGE)
        c.drawString(72, DECK_H / 2 - 42, "California residential real estate · September 2026")
        c.setFont(SANS, 10.5)
        c.setFillColor(SAND)
        c.drawString(72, 70, "Riddhi Shedge  ·  riddh1.shedg6@gmail.com")

    def head(self, kicker, title, dark=False):
        c = self.c
        if self.n > 0:
            c.showPage()  # close the previous slide before starting this one
        self._chrome(dark=dark)
        c.setFont(SANS_B, 10.5)
        c.setFillColor(SAND if dark else SAGE)
        c.drawString(70, DECK_H - 74, kicker.upper())
        c.setFont(SERIF_B, 30)
        c.setFillColor(CREAM if dark else PINE)
        c.drawString(70, DECK_H - 112, title)
        return DECK_H - 158

    def bullets(self, items, y, x=70, width=DECK_W - 140, size=13, gap=10, dark=False):
        c = self.c
        for head_text, body in items:
            c.setFillColor(SAND)
            c.setFont(SANS_B, size)
            c.drawString(x, y, "▸")
            if head_text:
                c.setFillColor(CREAM if dark else INK)
                c.setFont(SANS_B, size)
                c.drawString(x + 20, y, head_text)
                y -= size * 1.45
                y = wrap(self.c, body, x + 20, y, width - 20, size=size - 1.5,
                         color=(colors.HexColor("#b9c8bf") if dark else MUTED))
            else:
                y = wrap(self.c, body, x + 20, y, width - 20, size=size,
                         color=(CREAM if dark else INK))
            y -= gap
        return y

    def stats_row(self, stats, y):
        c = self.c
        n = len(stats)
        span = (DECK_W - 140) / n
        for i, (num, label) in enumerate(stats):
            x = 70 + i * span
            c.setFillColor(PINE)
            c.setFont(SERIF_B, 40)
            c.drawString(x, y, num)
            wrap(self.c, label, x, y - 24, span - 24, size=10.5, color=MUTED)
        return y - 70


def build_deck(out: Path) -> None:
    d = Deck(out)
    c = d.c

    # 1 · Title
    d.title_slide()

    # 2 · Problem
    y = d.head("The problem", "One exhausted human holds every deal together")
    y = d.bullets([
        ("40+ documents per transaction.",
         "Purchase agreement, counters, disclosures, reports, contingency removals. The terms that matter are buried in prose."),
        ("Deadlines are computed, not listed.",
         "Deposit in 3 business days. Inspection contingency day 17. Everything counts from acceptance, under California's rules, and recomputes when a counter changes the terms."),
        ("Real liability.",
         "A missed notice or a lapsed contingency costs deposits and draws lawsuits. TCs carry it for $350-450 a file."),
    ], y)

    # 3 · Status quo
    y = d.head("Status quo", "Today's software tracks tasks. Nobody reads the deal.")
    y = d.bullets([
        ("Checklists and reminders.",
         "Open To Close, SkySlope, ListedKit: templates the TC fills in and dates the TC types. The reading and the math stay in her head."),
        ("AI intake is arriving, trust is not.",
         "New tools extract fields from contracts. None shows the quote behind a value, flags what it isn't sure of, or gates what the AI can do with what it read."),
        ("The bar is a license, not a demo.",
         "A TC bets her reputation on every date. Tooling she can't audit is tooling she re-checks by hand, which is no tooling at all."),
    ], y)

    # 4 · Product
    y = d.head("Product", "Terra reads the deal and shows its work")
    y = d.bullets([
        ("Reads every document, with receipts.",
         "Each extracted term carries the verbatim quote it came from. Low confidence is flagged for human verification, never guessed."),
        ("Computes the obligations.",
         "Deadlines derive from the contract's own terms under the current CA purchase agreement rules, and recompute when a counter supersedes them."),
        ("Drafts, never sends.",
         "Chases, status updates, and notices are drafted with the reason attached. A human approves every send, one loop, no exceptions."),
        ("Every party gets a window.",
         "Buyer, seller, agents, escrow, lender: one link each, scoped to exactly their piece, including wire-fraud verification before any deposit step."),
    ], y)

    # 5 · Trust architecture (dark)
    y = d.head("Why Terra is different", "Five rules, enforced in code, not policy", dark=True)
    y = d.bullets([
        (None, "California residential only. The deadline law is the moat, so the wedge is the state with the hardest rules."),
        (None, "Money and wiring data are unrepresentable. The schema cannot store them; that is where the fraud lives."),
        (None, "Nothing sends without a human. One approval loop guards every outbound message."),
        (None, "Every extracted term is human-confirmed before it drives a deadline."),
        (None, "An append-only audit log the database itself refuses to edit."),
    ], y, size=14, gap=12, dark=True)

    # 6 · How it works
    y = d.head("How it works", "Email in, obligations out")
    steps = ["Email arrives", "Read + evidence", "Human confirms", "Deadline engine", "Draft + approve", "Audit log"]
    box_w = (DECK_W - 140 - 5 * 18) / 6
    x = 70
    yy = y - 40
    for i, s in enumerate(steps):
        c.setFillColor(CREAM)
        c.setStrokeColor(SAGE)
        c.roundRect(x, yy, box_w, 64, 9, stroke=1, fill=1)
        c.setFillColor(PINE)
        c.setFont(SANS_B, 11)
        # center the label (up to two lines)
        parts = s.split(" + ")
        if len(parts) == 2:
            c.drawCentredString(x + box_w / 2, yy + 38, parts[0] + " +")
            c.drawCentredString(x + box_w / 2, yy + 22, parts[1])
        else:
            words = s.split()
            if len(words) > 1 and c.stringWidth(s, SANS_B, 11) > box_w - 12:
                c.drawCentredString(x + box_w / 2, yy + 38, words[0])
                c.drawCentredString(x + box_w / 2, yy + 22, " ".join(words[1:]))
            else:
                c.drawCentredString(x + box_w / 2, yy + 30, s)
        if i < 5:
            c.setFillColor(SAND)
            c.setFont(SANS_B, 14)
            c.drawString(x + box_w + 4, yy + 26, "→")
        x += box_w + 18
    wrap(c, "A TC forwards or BCCs deal email to her Terra address. Terra classifies and reads "
            "the attachments, she confirms the terms, the CA engine computes the clock, and the "
            "drafts queue for her approval. Every step lands in the audit trail.",
         70, yy - 34, DECK_W - 140, size=12, color=MUTED)

    # 7 · Market
    y = d.head("Market", "Start where the rules are hardest")
    y = d.stats_row([
        ("1 in 8", "US residential transactions happen in California"),
        ("$350-450", "what a TC earns per file today"),
        ("$30-100/mo", "what TCs pay for software that doesn't read anything"),
    ], y - 26)
    y = d.bullets([
        ("Per-file pricing, where the value is.",
         "Terra charges like TCs earn: per file closed. ListedKit already proved per-contract intake pricing; Terra prices the whole obligation engine."),
        ("The wedge generalizes.",
         "The verified ruleset is a swappable module. State two is a ruleset project, not a rewrite."),
    ], y - 6)

    # 8 · Traction / status
    y = d.head("Where it stands", "Built, deployed, and hardened, honestly pre-revenue")
    y = d.bullets([
        ("Live product, not a prototype.",
         "Deployed multi-tenant workspaces: teammate invites, mandatory MFA, per-workspace send allowlists, org-scoped everything."),
        ("Engineering discipline unusual this early.",
         "579 backend tests including a CI attack-test that tries every route cross-tenant; extraction evals scored on real recorded documents; append-only audit verified live."),
        ("Privacy posture first.",
         "Demo runs synthetic data until the model-side zero-data-retention agreement is countersigned. Real client files only after."),
        ("Next: design partners.",
         "Recruiting 3-5 working California TCs now; pilot goal is time-to-file and deadline-catch metrics on real transactions."),
    ], y)

    # 9 · Business model
    y = d.head("Business model", "Priced per file, expanded per seat")
    y = d.bullets([
        ("Solo TCs: ~$20 per closed file.",
         "A working TC closes 8-20 files a month; Terra costs less than 6% of one file fee and reads everything she'd reread at midnight."),
        ("Teams and brokerages: seats + compliance.",
         "Workspace tiers, broker close-out packets, and the audit trail brokerages already pay SkySlope for, except computed instead of collected."),
        ("Expansion is built in.",
         "Every party touchpoint (buyer, seller, lender views) is a surface agents ask their own TCs about."),
    ], y)

    # 10 · Roadmap
    y = d.head("Roadmap", "Pilots, then revenue, then state two")
    y = d.bullets([
        ("Now to +3 months.", "3-5 CA design partners on real files; instrument time-to-file and extraction acceptance; first paid conversion."),
        ("+3 to +9 months.", "Self-serve onboarding for CA TCs, e-signature ecosystem integrations, brokerage tier, SOC 2 Type I when the first brokerage deal is in pipeline."),
        ("+9 months on.", "Second state ruleset, incumbent integrations as the acquisition surface (Lone Wolf, SkySlope, title companies)."),
    ], y)

    # 11 · Ask (dark)
    y = d.head("The ask", "Pilots and a pre-seed conversation", dark=True)
    y = d.bullets([
        (None, "Introductions to working California TCs and brokerage operators, for design-partner pilots."),
        (None, "Early pre-seed conversations: proptech pre-seeds averaged roughly $900K in H1 2026, and that funds pilots through revenue."),
        (None, "Riddhi Shedge  ·  riddh1.shedg6@gmail.com"),
    ], y, size=15, gap=14, dark=True)

    c.save()


def main() -> int:
    outdir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    outdir.mkdir(parents=True, exist_ok=True)
    one = outdir / "Terra One-Pager.pdf"
    deck = outdir / "Terra Pitch Deck.pdf"
    build_one_pager(one)
    build_deck(deck)
    print(f"wrote {one}\nwrote {deck}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
