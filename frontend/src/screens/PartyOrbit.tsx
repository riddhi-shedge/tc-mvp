import { useEffect, useRef, useState } from "react";
import { DashboardPartyView, DealParty, PARTY_ROLE_LABEL } from "../lib/api";
import { Icon } from "../lib/icons";

// Role → tint (by tier), so the orbit reads at a glance.
const TINT: Record<string, string> = {
  buyer: "#5257ea", seller: "#0e9488",
  buyer_agent: "#c07512", listing_agent: "#c07512",
  escrow: "#5b6472", title: "#5b6472", lender: "#5b6472",
  inspector_general: "#8457d6", appraiser: "#8457d6",
};
const tint = (role: string) => TINT[role] ?? "#5b6472";
function initials(name: string | null, role: string): string {
  const s = (name || role || "?").trim().split(/\s+/);
  return ((s[0]?.[0] ?? "") + (s[1]?.[0] ?? "")).toUpperCase() || "?";
}

// Concentric tiers, innermost first. Each lists the roles that belong on it; a
// filled party sits here, and any listed role with no party shows as an "add" seat.
const TIERS: { roles: string[]; labels: Record<string, string> }[] = [
  { roles: ["buyer", "seller"], labels: { buyer: "Buyer", seller: "Seller" } },
  { roles: ["buyer_agent", "listing_agent"], labels: { buyer_agent: "Buyer's agent", listing_agent: "Listing agent" } },
  {
    roles: ["escrow", "title", "lender", "inspector_general", "appraiser"],
    labels: { escrow: "Escrow", title: "Title", lender: "Lender", inspector_general: "Inspector", appraiser: "Appraiser" },
  },
];

type Seat = { key: string; role: string; label: string; pv?: DashboardPartyView };

function seatsForTier(tier: (typeof TIERS)[number], views: DashboardPartyView[]): Seat[] {
  const filled = views.filter((v) => tier.roles.includes(v.party.role));
  const presentRoles = new Set(filled.map((v) => v.party.role));
  const empties = tier.roles
    .filter((r) => !presentRoles.has(r))
    .map<Seat>((r) => ({ key: `empty-${r}`, role: r, label: tier.labels[r] ?? r }));
  return [
    ...filled.map<Seat>((pv) => ({ key: pv.party.id, role: pv.party.role, label: PARTY_ROLE_LABEL[pv.party.role] ?? pv.party.role, pv })),
    ...empties,
  ];
}

/** The orbital deal system: the property at the exact center, everyone orbiting on
 *  tiers (principals · agents · escrow/title/lender/vendors). Auto-rotates, freezes
 *  on hover so you can click. Ring radii are derived so nodes never overlap. */
export function PartyOrbit({
  views,
  onSelect,
  onAddRole,
  dragging = false,
  onDropTask,
}: {
  views: DashboardPartyView[];
  onSelect: (pv: DashboardPartyView) => void;
  onAddRole: (role: string) => void;
  dragging?: boolean;
  onDropTask?: (party: DealParty) => void;
}) {
  const stageRef = useRef<HTMLDivElement>(null);
  const paused = useRef(false);
  const draggingRef = useRef(false);
  draggingRef.current = dragging; // freeze the orbit while a task is being dragged
  const [dropId, setDropId] = useState<string | null>(null);

  const tiers = TIERS.map((t) => seatsForTier(t, views));

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const nodeEls = Array.from(stage.querySelectorAll<HTMLElement>(".orb-node"));
    const lines = stage.querySelector<SVGSVGElement>(".orb-lines");

    // Per-tier rotation speed (deg/s) and current angle; alternate direction.
    const speeds = [6, -4.2, 3];
    const angles = [0, -15, 24];
    let radii = [110, 193, 276];

    function layout() {
      const w = stage!.clientWidth;
      const h = stage!.clientHeight;
      // Fit the whole system to the shorter half, then space the rings PROPORTIONALLY
      // (0.40 / 0.70 / 1.0) and shrink the nodes with the radius (--oscale). The ring
      // gap is always 0.30·maxR while a node is ~0.27·maxR tall, so radially-aligned
      // nodes on adjacent rings never touch — at any container size (e.g. the narrower
      // orbit column in the split layout).
      const maxR = Math.max(140, Math.min(h / 2 - 40, w / 2 - 24, 300));
      radii = [maxR * 0.4, maxR * 0.7, maxR];
      const scale = Math.max(0.62, Math.min(1, maxR / 276));
      stage!.style.setProperty("--oscale", String(scale));
      if (lines) {
        lines.innerHTML = radii
          .map((r) => `<circle cx="50%" cy="50%" r="${r}" />`)
          .join("");
      }
    }
    layout();
    const ro = new ResizeObserver(layout);
    ro.observe(stage);

    let raf = 0;
    let last = performance.now();
    function tick(t: number) {
      const dt = Math.min((t - last) / 1000, 0.05);
      last = t;
      if (!paused.current && !draggingRef.current) speeds.forEach((s, i) => (angles[i] += s * dt));
      for (const el of nodeEls) {
        const ring = Number(el.dataset.ring);
        const base = Number(el.dataset.base);
        const a = ((angles[ring] + base) * Math.PI) / 180;
        const r = radii[ring];
        el.style.transform = `translate(-50%, -50%) translate(${Math.cos(a) * r}px, ${Math.sin(a) * r}px)`;
      }
      raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [views]);

  return (
    <div
      className="orb-stage"
      ref={stageRef}
      onMouseEnter={() => (paused.current = true)}
      onMouseLeave={() => (paused.current = false)}
    >
      <svg className="orb-lines" aria-hidden="true" />
      <div className="orb-center" aria-hidden="true">
        <Icon name="home" size={30} />
        <div className="orb-addr">1057 Foxglove Pl</div>
        <div className="orb-sub">the deal</div>
      </div>

      {tiers.flatMap((seats, ring) =>
        seats.map((seat, i) => {
          const base = (360 / seats.length) * i;
          const open = seat.pv?.open_tasks.length ?? 0;
          const canDrop = dragging && !!seat.pv;
          return (
            <div
              key={seat.key}
              className={`orb-node ${seat.pv ? "" : "empty"} ${canDrop ? "droppable" : ""} ${dropId === seat.key ? "dropon" : ""}`}
              data-ring={ring}
              data-base={base}
              onClick={() => (seat.pv ? onSelect(seat.pv) : onAddRole(seat.role))}
              title={seat.pv ? `${seat.pv.party.name ?? seat.label}` : `Add ${seat.label.toLowerCase()}`}
              onDragOver={canDrop ? (e) => { e.preventDefault(); setDropId(seat.key); } : undefined}
              onDragLeave={canDrop ? () => setDropId((d) => (d === seat.key ? null : d)) : undefined}
              onDrop={
                canDrop
                  ? (e) => { e.preventDefault(); onDropTask?.(seat.pv!.party); setDropId(null); }
                  : undefined
              }
            >
              <div className="orb-ava" style={seat.pv ? { background: tint(seat.role) } : undefined}>
                {seat.pv ? initials(seat.pv.party.name, seat.role) : <Icon name="plus" size={16} />}
                {open > 0 && <span className="orb-badge">{open}</span>}
              </div>
              {seat.pv ? (
                <>
                  <div className="orb-name">{(seat.pv.party.name ?? "").split(" ")[0] || seat.label}</div>
                  <div className="orb-role">{seat.label}</div>
                </>
              ) : (
                <div className="orb-role add">Add {seat.label.toLowerCase()}</div>
              )}
            </div>
          );
        }),
      )}
    </div>
  );
}
