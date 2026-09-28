# Terra Demo Script

Ten minutes, live. Written for: Riddhi, presenting Terra to investors, TCs, or partners.

App: https://terra-frontend-ujk2.onrender.com · Sign in: demo@tcmvp.test + authenticator

---

## Before the demo (5 minutes, every time)

1. **Reset the golden deal** so the data is fresh and the dates are current:
   `cd tc-mvp/backend && PYTHONPATH=. .venv/bin/python scripts/seed_demo_deal.py`
   This rebuilds "4285 Alder Creek Way, Sacramento" with today-relative deadlines,
   4 drafts awaiting approval, a served NBP, a counter offer, and 3 risk flags.
2. **Wake the backend**: open the app and log in ~5 minutes before you present
   (free tier sleeps; first load can take 50 seconds). Leave the tab open.
3. **Theme**: present in light mode unless the room is dark.
4. **Optional, for the live-send beat**: on the demo deal's Parties tab, set the
   lender's email to your own allowlisted address so Approve & Send delivers a
   real email you can open on your phone.
5. **Fallback**: keep the 3-minute recorded demo on the desktop. If wifi or the
   host hiccups, play it without apologizing.

---

## The demo (talk track in quotes, actions in brackets)

### 1. Cold open — the landing page (45 seconds)

"Every California home sale runs on one exhausted person: the transaction
coordinator. Forty documents, a dozen deadlines, real liability. This is Terra."

[Point at the approve-loop demo on the login page; click Approve & Send.]

"That button is the whole philosophy. Terra reads, computes, and drafts.
A human approves everything that leaves. Nothing auto-sends, ever."

[Sign in. Authenticator code: mention MFA is mandatory, not optional.]

### 2. Home — the decision queue (1 minute)

"This is a TC's morning. Not a checklist she wrote, a queue Terra computed:
drafts waiting for her approval, deadlines inside the danger window, risk
flags from reading the documents themselves."

[Hover the bell count. Scroll the deadline horizon. Click one risk flag,
read it aloud: it's specific, not generic.]

### 3. The deal — evidence, not vibes (3 minutes — the core)

[Open 4285 Alder Creek Way. Land on the timeline.]

"Terra read the signed purchase agreement and computed every date from the
contract's own terms under the current CA purchase agreement rules: deposit in
3 business days, inspection contingency day 17, loan day 21, close day 45.
These aren't reminders someone typed. They're computed, and they recompute
when terms change."

[Documents tab. Open the purchase agreement's fields. Click a ❝ evidence mark.]

"Every extracted value carries the exact quote it came from. This is the
difference between an AI that summarizes and an AI a licensed professional
can rely on: you can audit every single number back to the page."

[Find the APN field, flagged low-confidence.]

"And when Terra isn't sure, it says so. The scan is ambiguous here, so it's
flagged instead of guessed. I verify it, type the correction, and now it's a
human-confirmed fact." [Fix it live: 277-0413-021.]

[Point at the price: $925,000.]

"The seller countered. Terra read the counter, and the new price supersedes
the original everywhere, with the paper trail preserved. Ask any TC about the
deal where someone worked off the un-countered price."

### 4. Approve & Send — the trust moment (2 minutes)

[Back to Home. Open the lender-status draft in the queue.]

"The loan contingency is coming up and there's no lender status on file, so
Terra drafted the chase. Here's the draft, here's *why* it drafted it, and
here's the only send button in the product."

[Either: approve and show the email arriving on your phone — or attempt the
send to the synthetic address and let Terra refuse:]

"Notice it refused. The recipient isn't on this workspace's approved list.
Terra fails closed. Same design everywhere: money and wiring details are
unrepresentable in the system, by schema, because that's where the fraud is."

### 5. The other side of the table (1.5 minutes)

[Workspace tab: show invite links. Open the buyer's link in a private window.]

"Every party gets their own scoped view from a single link. No login, no
sight of anyone else's tasks. The buyer sees where the deal stands and, when
it's time to wire their deposit, this:" [show the wire-fraud interstitial]
"a forced call-escrow-to-verify step. Wire fraud costs buyers hundreds of
millions a year. Terra's answer is out-of-band verification, built in."

### 6. Close-out (1 minute)

[Broker file: click Checklist, then Print close-out packet (show preview).]

"When it closes, the broker's audit file assembles itself, checked against the
CA compliance set, printable as one packet."

### 7. Close (30 seconds)

"Five rules are enforced in code, not policy: California residential only.
No money or wiring data, unrepresentable. Nothing sends without a human.
Every extracted term is human-confirmed before it drives a deadline. And every
action lands in an append-only audit log the database itself won't let anyone
edit. That's Terra: an AI coordinator built like the liability is real,
because it is."

---

## Q&A ammunition

- **"What if the AI is wrong?"** Show the evidence quote + confidence + the
  confirm gate. Nothing drives a deadline until a human confirms it.
- **"Why only California?"** One in eight US transactions; the deadline law is
  the hard part and it's state-specific. The ruleset is swappable by design.
- **"What about my email/e-sign stack?"** Documents arrive by forwarding an
  email; nothing changes about DocuSign/zipForm. Terra reads outputs.
- **"Data privacy?"** Zero-data-retention posture on model calls; the deployed
  demo runs synthetic data only until the ZDR agreement is countersigned.
- **"How is this different from Open To Close / SkySlope?"** They manage
  checklists. Terra reads the documents and computes the obligations, with
  provenance. Nobody else shows you the quote behind every number.

## Known rough edges (never demo these)

- Deal summary / story generation needs a warm model call; do not click it on
  stage unless you've tested it that morning.
- The Quarter page is real-data-only now; with one demo deal it looks sparse.
- Party invite links: mint fresh ones after each reseed (old links die with
  the deleted deal).
