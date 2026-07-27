/* Professional line-icon set (Lucide-style, stroke = currentColor). One place so
 * the whole app shares a consistent, non-emoji visual language. */
import { SVGProps } from "react";

const P = (d: string) => d;

// Each icon is a list of <path>/<circle>/… children as raw JSX-safe primitives,
// authored as SVG child-element strings drawn at 24×24 and scaled by `size`.
const PATHS: Record<string, string[]> = {
  home: [P("M3 10.5 12 3l9 7.5"), P("M5 9.5V21h14V9.5"), P("M9.5 21v-6h5v6")],
  deals: [P("M4 6h16"), P("M4 12h16"), P("M4 18h10")],
  board: [P("M4 5h5v14H4z"), P("M10.5 5h5v9h-5z"), P("M17 5h3v6h-3z")],
  calendar: [P("M4 6h16v14H4z"), P("M4 10h16"), P("M8 3v4"), P("M16 3v4")],
  clock: [P("M12 7v5l3 2"), "circle:12,12,8"],
  check: [P("M5 12.5l4.2 4.2L19 7")],
  checkCircle: ["circle:12,12,8", P("M8.5 12.2l2.4 2.4L16 9.5")],
  warning: [P("M12 4 2.5 20h19z"), P("M12 10v5"), P("M12 18h.01")],
  flag: [P("M6 21V4"), P("M6 4h11l-2 4 2 4H6")],
  mail: [P("M4 6h16v12H4z"), P("M4 7l8 6 8-6")],
  phone: [P("M6 3h3l2 5-2 1a12 12 0 0 0 5 5l1-2 5 2v3a2 2 0 0 1-2 2A16 16 0 0 1 4 5a2 2 0 0 1 2-2Z")],
  key: ["circle:8,15,4", P("M11 12l8-8"), P("M16 4l3 3"), P("M13 7l3 3")],
  shield: [P("M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6z"), P("M9 12l2 2 4-4")],
  search: ["circle:11,11,6", P("M20 20l-3.5-3.5")],
  pin: [P("M12 21s7-6.2 7-11a7 7 0 1 0-14 0c0 4.8 7 11 7 11z"), "circle:12,10,2.5"],
  clipboard: [P("M8 5H6v15h12V5h-2"), P("M9 3h6v3H9z")],
  tag: [P("M4 4h7l9 9-7 7-9-9z"), "circle:8.5,8.5,1.3"],
  bank: [P("M4 10h16"), P("M4 10 12 4l8 6"), P("M6 10v8"), P("M10 10v8"), P("M14 10v8"), P("M18 10v8"), P("M4 20h16")],
  receipt: [P("M6 3h12v18l-3-2-3 2-3-2-3 2z"), P("M9 8h6"), P("M9 12h6")],
  doc: [P("M7 3h7l4 4v14H7z"), P("M14 3v4h4"), P("M10 13h5"), P("M10 16h5")],
  folder: [P("M4 7h6l2 2h8v10H4z")],
  users: ["circle:9,8,3", P("M4 20a5 5 0 0 1 10 0"), P("M16 6a3 3 0 0 1 0 6"), P("M15 20a5 5 0 0 0 5-5")],
  user: ["circle:12,8,3.2", P("M5.5 20a6.5 6.5 0 0 1 13 0")],
  money: [P("M4 6h16v12H4z"), "circle:12,12,2.6", P("M7 9v6"), P("M17 9v6")],
  hourglass: [P("M6 3h12"), P("M6 21h12"), P("M7 3c0 5 10 5 10 0"), P("M7 21c0-5 10-5 10 0")],
  card: [P("M3 6h18v12H3z"), P("M3 10h18"), P("M6 14h4")],
  attach: [P("M20 11l-8.5 8.5a4 4 0 0 1-6-6L14 5a2.7 2.7 0 0 1 4 4l-8.5 8.5a1.4 1.4 0 0 1-2-2L14 8")],
  inbox: [P("M4 13l2.5-8h11L20 13v6H4z"), P("M4 13h4l1.5 2.5h5L16 13h4")],
  lock: [P("M6 11h12v9H6z"), P("M9 11V8a3 3 0 0 1 6 0v3")],
  sparkle: [P("M12 4l1.6 4.8L18 10l-4.4 1.2L12 16l-1.6-4.8L6 10l4.4-1.2z")],
  spark: [P("M12 3v4"), P("M12 17v4"), P("M3 12h4"), P("M17 12h4"), P("M6 6l2.5 2.5"), P("M15.5 15.5 18 18")],
  chevron: [P("M9 6l6 6-6 6")],
  plus: [P("M12 5v14"), P("M5 12h14")],
  x: [P("M6 6l12 12"), P("M18 6 6 18")],
};

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 16, ...rest }: { name: IconName; size?: number } & SVGProps<SVGSVGElement>) {
  const items = PATHS[name] ?? [];
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ flex: "0 0 auto", display: "inline-block", verticalAlign: "-0.15em" }}
      {...rest}
    >
      {items.map((it, i) =>
        it.startsWith("circle:")
          ? (() => {
              const [cx, cy, r] = it.slice(7).split(",");
              return <circle key={i} cx={cx} cy={cy} r={r} />;
            })()
          : <path key={i} d={it} />,
      )}
    </svg>
  );
}
