import { IconName } from "../../lib/icons";

/** Distinct visual identity per party archetype — accent, icon, and hero copy.
 *  The archetype comes from the backend (/party/workspace), which maps every role
 *  onto one of these. `default` catches any not-yet-tailored role. */
export type RoleTheme = {
  accent: string; // drives --role-accent
  soft: string; // translucent accent for backgrounds
  icon: IconName;
  eyebrow: string;
  greeting: (name: string | null) => string;
  tagline: string;
};

export const ROLE_THEMES: Record<string, RoleTheme> = {
  buyer: {
    accent: "#5257ea", soft: "#5257ea1a", icon: "home",
    eyebrow: "Your future home",
    greeting: (n) => `Welcome${n ? `, ${n.split(" ")[0]}` : ""}`,
    tagline: "Everything about your new home — the details, the money, and what happens next.",
  },
  seller: {
    accent: "#0e9488", soft: "#0e94881a", icon: "key",
    eyebrow: "Your sale",
    greeting: (n) => `Hi${n ? `, ${n.split(" ")[0]}` : ""}`,
    tagline: "Where your sale stands, the buyer's progress, and what needs you.",
  },
  escrow: {
    accent: "#4f5a6a", soft: "#4f5a6a1a", icon: "bank",
    eyebrow: "Escrow file",
    greeting: (n) => n ?? "Escrow file",
    tagline: "The closing file — figures, parties, and what's still outstanding to close.",
  },
  inspector: {
    accent: "#b8720f", soft: "#b8720f1a", icon: "clipboard",
    eyebrow: "Your inspection",
    greeting: (n) => `Hi${n ? `, ${n.split(" ")[0]}` : ""}`,
    tagline: "Your inspection for this property — complete it and upload your report.",
  },
  lender: {
    accent: "#2563a8", soft: "#2563a81a", icon: "money",
    eyebrow: "Loan file",
    greeting: (n) => `Hi${n ? `, ${n.split(" ")[0]}` : ""}`,
    tagline: "The loan picture for this deal and your outstanding items.",
  },
  agent: {
    accent: "#c07512", soft: "#c075121a", icon: "contract",
    eyebrow: "Deal cockpit",
    greeting: (n) => `Hi${n ? `, ${n.split(" ")[0]}` : ""}`,
    tagline: "The full deal — dates, terms, parties, and your tasks.",
  },
  default: {
    accent: "#8457d6", soft: "#8457d61a", icon: "folder",
    eyebrow: "Your workspace",
    greeting: (n) => `Hi${n ? `, ${n.split(" ")[0]}` : ""}`,
    tagline: "Where the deal stands and what needs you.",
  },
};

export const themeFor = (archetype: string): RoleTheme => ROLE_THEMES[archetype] ?? ROLE_THEMES.default;
