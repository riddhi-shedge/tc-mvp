import { fmtDate } from "../../../lib/format";
import { DISCLOSURE_COPY } from "../buyer/caLibrary";
import { daysTo } from "../helpers";
import { Workspace } from "../types";
import { Disclosure, DisclosureKind, SaleDeal, SellerPhase, SellerTask } from "./types";

const STAGE_PHASE: Record<string, SellerPhase> = {
  new: "disclosures", cont: "buyer_contingencies", closing: "closing", closed: "closed",
};

/** Currency from integer cents, e.g. 178220000 → "$1,782,200". */
export function usd(cents: number, withCents = false): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD",
    minimumFractionDigits: withCents ? 2 : 0, maximumFractionDigits: withCents ? 2 : 0,
  }).format(cents / 100);
}

function urgencyFor(due: string | null, done: boolean): SellerTask["urgency"] {
  if (done) return "later";
  const n = daysTo(due);
  if (n != null && n <= 2) return "now";
  if (n != null && n <= 7) return "soon";
  return "later";
}

/** Map the /party/workspace payload (+ static CA copy) onto the seller contracts. */
export function buildSaleDeal(ws: Workspace): SaleDeal {
  const coe = ws.deadlines.find((d) => /escrow|clos/i.test(d.name)) ?? null;
  const closeDate = coe?.due_date ?? null;

  const tasks: SellerTask[] = ws.my_tasks.map((t) => {
    const done = t.status === "done" || t.status === "complete";
    return { id: t.id, label: t.title, dueDate: t.due_date, done, urgency: urgencyFor(t.due_date, done) };
  });

  const disclosures: Disclosure[] = (ws.disclosures ?? []).map((d) => {
    const copy = DISCLOSURE_COPY[d.kind] ?? DISCLOSURE_COPY.other;
    return {
      id: d.id, kind: (d.kind as DisclosureKind), title: d.title, state: d.state,
      dueDate: d.dueDate, explanation: copy.explanation, stakes: copy.stakes,
    };
  });

  const dealHealth = ws.dealHealth ?? null;
  const netSheet = ws.netSheet
    ? { ...ws.netSheet, beforeMortgagePayoff: ws.netSheet.beforeMortgagePayoff ?? false }
    : null;

  // Status line — the seller's glance: will it close, and what's the next obligation.
  const undelivered = disclosures.filter((d) => d.state === "draft" || d.state === "completed");
  const openTasks = tasks.filter((t) => !t.done);
  const overdue = openTasks.filter((t) => (daysTo(t.dueDate) ?? 1) < 0);
  const level =
    dealHealth?.meter === "at_risk" ? "at_risk"
    : undelivered.length || overdue.length || dealHealth?.meter === "watch" ? "action_soon"
    : "on_track";
  const nextActionLabel = undelivered.length
    ? `Deliver ${undelivered.length} seller disclosure${undelivered.length > 1 ? "s" : ""} to the buyer`
    : openTasks[0] ? openTasks[0].label
    : closeDate ? `On track to close ${fmtDate(closeDate)}` : "You're on track";

  return {
    summary: {
      propertyAddress: ws.property?.address ?? "Your home",
      heroPhotoUrl: ws.property?.photo_url ?? null,
      photoCount: ws.property?.photo_url ? 1 : 0,
      phase: STAGE_PHASE[ws.stage ?? ""] ?? "escrow_open",
      closeDate,
      daysToClose: daysTo(closeDate),
      estimatedNetProceedsCents: netSheet?.estimatedNetProceedsCents ?? null,
      beforeMortgagePayoff: netSheet?.beforeMortgagePayoff ?? false,
      status: { level, nextActionLabel },
    },
    dealHealth,
    disclosures,
    netSheet,
    requests: ws.requests ?? [],
    tasks,
    team: ws.roster,
    activity: ws.activity ?? [],
  };
}
