import { fmtDate } from "../../../lib/format";
import { daysTo } from "../helpers";
import { CONTINGENCY_COPY } from "./caLibrary";
import { BuyerDeal, BuyerTask, Contingency, ContingencyKind, DealPhase, DepositStep, BuyerWorkspacePayload } from "./types";

const STAGE_PHASE: Record<string, DealPhase> = {
  new: "escrow_open", cont: "contingencies", closing: "closing", closed: "keys",
};
const CONTINGENCY_KINDS: [ContingencyKind, string][] = [
  ["inspection", "Inspection contingency"], ["loan", "Loan contingency"], ["appraisal", "Appraisal contingency"],
];

/** acceptance_date is stored MM/DD/YYYY; return a local Date (or null). */
function parseDate(s: string | undefined): Date | null {
  if (!s) return null;
  const m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})/.exec(s.trim());
  if (m) return new Date(Number(m[3]), Number(m[1]) - 1, Number(m[2]));
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}
const toISO = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function urgencyFor(due: string | null, done: boolean): BuyerTask["urgency"] {
  if (done) return "later";
  const n = daysTo(due);
  if (n != null && n <= 2) return "now";
  if (n != null && n <= 7) return "soon";
  return "later";
}

/** Map the /party/workspace payload (+ static CA copy) onto the buyer contracts. */
export function buildBuyerDeal(ws: BuyerWorkspacePayload): BuyerDeal {
  const coe = ws.deadlines.find((d) => /escrow|clos/i.test(d.name)) ?? null;
  const keysDate = coe?.due_date ?? null;

  const tasks: BuyerTask[] = ws.my_tasks.map((t) => ({
    id: t.id, label: t.title, dueDate: t.due_date,
    done: t.status === "done" || t.status === "complete",
    urgency: urgencyFor(t.due_date, t.status === "done" || t.status === "complete"),
  }));

  // status line — answers "where are we / what do I owe" from the next obligation
  const openTasks = tasks.filter((t) => !t.done);
  const overdue = openTasks.filter((t) => (daysTo(t.dueDate) ?? 1) < 0);
  const upcoming = [
    ...openTasks.filter((t) => t.dueDate && (daysTo(t.dueDate) ?? -1) >= 0).map((t) => ({ label: t.label, date: t.dueDate! })),
    ...ws.deadlines.filter((d) => (daysTo(d.due_date) ?? -1) >= 0).map((d) => ({ label: d.name, date: d.due_date })),
  ].sort((a, b) => a.date.localeCompare(b.date));
  const next = upcoming[0] ?? null;
  const level = overdue.length ? "at_risk" : next && (daysTo(next.date) ?? 99) <= 5 ? "action_soon" : "on_track";
  const nextActionLabel = overdue.length
    ? `${overdue[0].label} — overdue`
    : next ? `${next.label} · ${fmtDate(next.date)}` : "You're all set for now";

  // Contingencies live in the extracted fields (`<kind>_contingency_present` /
  // `<kind>_contingency_days`), not the deadline list. Show each so the buyer can
  // see, plainly, which protections they have and which were waived.
  const f = ws.fields;
  const acceptance = parseDate(f.acceptance_date);
  const contingencies: Contingency[] = [];
  for (const [kind, title] of CONTINGENCY_KINDS) {
    const present = f[`${kind}_contingency_present`];
    const daysRaw = f[`${kind}_contingency_days`];
    if (present === undefined && daysRaw === undefined) continue;
    const waived = present === "false" || (!!daysRaw && /removed|waived|none|n\/?a/i.test(daysRaw));
    let removalDate: string | null = null;
    let daysLeft: number | null = null;
    if (!waived) {
      const dnum = daysRaw ? parseInt(daysRaw, 10) : NaN;
      if (!Number.isNaN(dnum) && acceptance) {
        const dt = new Date(acceptance); dt.setDate(dt.getDate() + dnum);
        removalDate = toISO(dt); daysLeft = daysTo(removalDate);
      }
    }
    contingencies.push({
      id: kind, kind, title,
      status: waived ? "removed" : "active",
      removalDate, daysLeft,
      explanation: CONTINGENCY_COPY[kind].explanation, stakes: CONTINGENCY_COPY[kind].stakes,
    });
  }

  let deposit: DepositStep | null = null;
  if (ws.deposit) {
    const escrow = ws.roster.find((m) => m.id === ws.deposit!.escrowContactId) ?? ws.roster.find((m) => m.role === "escrow");
    deposit = {
      // Show just the figure in the big display; drop any "(3% of price)" aside.
      amountLabel: ws.deposit.amount.replace(/\s*\(.*$/, "").trim() || ws.deposit.amount,
      payeeLabel: ws.deposit.payee, dueDate: ws.deposit.dueDate,
      verifiedByBuyer: ws.deposit.verifiedByBuyer, escrowPhone: escrow?.phone ?? null,
    };
  }

  return {
    summary: {
      propertyAddress: ws.property?.address ?? "Your future home",
      heroPhotoUrl: ws.property?.photo_url ?? null,
      photoCount: ws.property?.photo_url ? 1 : 0,
      phase: STAGE_PHASE[ws.stage ?? ""] ?? "escrow_open",
      estimatedKeysDate: keysDate,
      daysToKeys: daysTo(keysDate),
      status: { level, nextActionLabel },
    },
    contingencies,
    deposit,
    tasks,
    team: ws.roster,
    activity: ws.activity ?? [],
  };
}
