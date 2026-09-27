// UI integrity gate: every statically-written className must have at least one
// rule in a stylesheet, and every <Icon name="..."> must exist in icons.tsx.
// Born from a shipped component (the ⌘K palette) that had ZERO css and
// rendered as raw text. Wrapper-hook classes with no rule are allowed only if
// listed below with a reason.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const ALLOWED_UNSTYLED = new Set([
  // benign wrapper hooks / suffix classes whose styling lives on children
  "aw-cc-docs", "aw-ms-ic", "bf-card", "bw-move-main", "bw-sec", "cal",
  "cal-runway", "ev", "ev-body", "iw-body", "iw-ticket-l", "iw-ticket-r",
  "lv", "lv-body", "lv-sub", "pk-head", "qtr", "tlr-card",
]);

function walk(dir, exts, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, exts, out);
    else if (exts.some((e) => p.endsWith(e))) out.push(p);
  }
  return out;
}

let css = "";
for (const f of walk("src", [".css"])) css += readFileSync(f, "utf8");
const defined = new Set([...css.matchAll(/\.([A-Za-z][\w-]*)/g)].map((m) => m[1]));

const iconsSrc = readFileSync("src/lib/icons.tsx", "utf8");
const iconNames = new Set(
  [...iconsSrc.matchAll(/^\s{2}([a-zA-Z][\w-]*):\s*\[/gm)].map((m) => m[1]),
);

const missing = new Map();
const badIcons = new Map();
for (const f of walk("src", [".tsx"])) {
  const text = readFileSync(f, "utf8");
  const classes = [];
  for (const m of text.matchAll(/className="([^"]+)"/g)) classes.push(...m[1].split(/\s+/));
  for (const m of text.matchAll(/className=\{`([^`]+)`\}/g))
    classes.push(...m[1].replace(/\$\{[^}]*\}/g, " ").split(/\s+/));
  for (const c of classes) {
    if (!c || c.endsWith("-")) continue; // dynamic-prefix fragment
    if (!defined.has(c) && !ALLOWED_UNSTYLED.has(c)) missing.set(c, f);
  }
  for (const m of text.matchAll(/<Icon\s+name="([\w-]+)"/g))
    if (!iconNames.has(m[1])) badIcons.set(m[1], f);
  for (const m of text.matchAll(/icon:\s*"([\w-]+)"/g))
    if (!iconNames.has(m[1])) badIcons.set(m[1], f);
}

let failed = false;
if (missing.size) {
  failed = true;
  console.error("Classes used with NO stylesheet rule (style them or allowlist with a reason):");
  for (const [c, f] of [...missing].sort()) console.error(`  ${c}  (${f})`);
}
if (badIcons.size) {
  failed = true;
  console.error("Icon names that do not exist in icons.tsx:");
  for (const [c, f] of [...badIcons].sort()) console.error(`  ${c}  (${f})`);
}
if (failed) process.exit(1);
console.log(`styles OK: all classes styled, ${iconNames.size} icons valid`);
