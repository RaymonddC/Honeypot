/**
 * The app's icon set — inline SVG, one shape per name.
 *
 * Why not Unicode glyphs (⬡ ⇌ ◉ ⚑ …), which this replaced: Hanken Grotesk
 * contains none of them, so every one fell back to whatever symbol font the OS
 * happened to provide — Segoe UI Symbol on Windows, Apple Symbols on macOS,
 * DejaVu on Linux. They rendered, but in a different face from the app and in a
 * different shape on each machine, so the same screen did not look the same on
 * two computers. An emoji-presentation glyph would also ignore currentColor.
 *
 * These are drawn on a 24×24 grid with a 1.6 stroke, round caps and joins, no
 * fill, and `stroke="currentColor"` — so an icon inherits its colour from the
 * text around it and tints with the accent like any other mark.
 */

export type IconName =
  // navigation / modules
  | "home"
  | "case"
  | "infiltrate"
  | "trace"
  | "takedown"
  | "uncover"
  | "commandCenter"
  | "honeypotOps"
  | "audit"
  | "users"
  | "roles"
  | "guide"
  | "settings"
  | "menu"
  | "search"
  // documents / actions
  | "freeze"
  | "document"
  | "alert"
  | "download"
  | "dispatch"
  // entities
  | "bank"
  | "wallet"
  | "phone"
  | "link"
  | "person"
  | "org"
  | "entity"
  // agencies
  | "exchange"
  | "regulator"
  | "police"
  // status
  | "check"
  | "cross"
  | "warning"
  | "plus"
  | "edit"
  | "reviewed"
  // graph viewport controls
  | "zoomIn"
  | "zoomOut"
  | "fit"
  | "reset";

/** Path data only — every icon shares the same grid, stroke and cap settings. */
const PATHS: Record<IconName, React.ReactNode> = {
  home: <path d="M4 10.5 12 4l8 6.5V19a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z" />,
  case: (
    <>
      <rect x="3.5" y="6" width="17" height="14" rx="2" />
      <path d="M9 6V4.5A1.5 1.5 0 0 1 10.5 3h3A1.5 1.5 0 0 1 15 4.5V6M3.5 11h17" />
    </>
  ),
  infiltrate: <path d="m12 3 7.5 4.5v9L12 21l-7.5-4.5v-9z" />,
  trace: <path d="M4 9h13l-3-3m6 9H7l3 3" />,
  takedown: (
    <>
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  uncover: <path d="M5 21V4h9l-1 3h6l-1.5 4.5L18 16H5" />,
  commandCenter: (
    <>
      <rect x="3.5" y="3.5" width="7" height="7" rx="1.2" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1.2" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1.2" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1.2" />
    </>
  ),
  honeypotOps: (
    <path d="M8.5 4.5 10 8l-2 2a12 12 0 0 0 6 6l2-2 3.5 1.5v3A1.5 1.5 0 0 1 18 20 15.5 15.5 0 0 1 4 6a1.5 1.5 0 0 1 1.5-1.5z" />
  ),
  audit: <path d="M10 14a4 4 0 0 0 6 .5l2.5-2.5a4 4 0 1 0-5.7-5.7L11.5 7.5M14 10a4 4 0 0 0-6-.5L5.5 12a4 4 0 1 0 5.7 5.7l1.3-1.3" />,
  users: (
    <>
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3.5 20a5.5 5.5 0 0 1 11 0M17 11.5a3 3 0 0 0 0-6M18 20a5 5 0 0 0-2.5-4.3" />
    </>
  ),
  roles: <path d="M12 3.5 19 6v6c0 4-3 7-7 8.5C8 19 5 16 5 12V6z" />,
  guide: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M9.7 9.5a2.4 2.4 0 1 1 3.2 2.3c-.6.2-.9.8-.9 1.4v.5" />
      <path d="M12 17h.01" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 14.5a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1v.3a2 2 0 1 1-4 0v-.2a1.6 1.6 0 0 0-2.8-1.1l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0-1.1-2.7h-.3a2 2 0 1 1 0-4h.2a1.6 1.6 0 0 0 1.1-2.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 2.7-1.1v-.3a2 2 0 1 1 4 0v.2a1.6 1.6 0 0 0 2.8 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0 1.1 2.7h.3a2 2 0 1 1 0 4h-.2a1.6 1.6 0 0 0-1.4 1z" />
    </>
  ),
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  search: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4 4" />
    </>
  ),

  freeze: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="m6 6 12 12" />
    </>
  ),
  document: (
    <>
      <path d="M6 3.5h7.5L18 8v12.5H6z" />
      <path d="M13 3.5V8h5M9 12.5h6M9 16h4" />
    </>
  ),
  alert: <path d="M12 4.5a5.5 5.5 0 0 0-5.5 5.5c0 4-2 5.5-2 5.5h15s-2-1.5-2-5.5A5.5 5.5 0 0 0 12 4.5M10.5 19a1.7 1.7 0 0 0 3 0" />,
  download: <path d="M12 4v11m0 0 4-4m-4 4-4-4M4.5 19.5h15" />,
  dispatch: <path d="M8 16 16 8m0 0H9.5M16 8v6.5" />,

  bank: <path d="M3.5 9.5 12 4.5l8.5 5M5.5 9.5v8M10 9.5v8M14 9.5v8M18.5 9.5v8M3.5 20.5h17" />,
  wallet: (
    <>
      <path d="M10 13.5a3.5 3.5 0 0 0 5 .3l2-2a3.5 3.5 0 0 0-5-5l-1 1" />
      <path d="M14 10.5a3.5 3.5 0 0 0-5-.3l-2 2a3.5 3.5 0 0 0 5 5l1-1" />
    </>
  ),
  phone: (
    <path d="M8.5 4.5 10 8l-2 2a12 12 0 0 0 6 6l2-2 3.5 1.5v3A1.5 1.5 0 0 1 18 20 15.5 15.5 0 0 1 4 6a1.5 1.5 0 0 1 1.5-1.5z" />
  ),
  link: (
    <>
      <path d="M14 5h5v5" />
      <path d="M19 5 10.5 13.5" />
      <path d="M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10" />
    </>
  ),
  person: (
    <>
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20a7 7 0 0 1 14 0" />
    </>
  ),
  org: (
    <>
      <path d="M4 20.5V6.5A1.5 1.5 0 0 1 5.5 5h7A1.5 1.5 0 0 1 14 6.5v14" />
      <path d="M14 11h4.5A1.5 1.5 0 0 1 20 12.5v8M3 20.5h18M7 9h4M7 13h4M7 17h4M17 15h1M17 18h1" />
    </>
  ),
  entity: <path d="m12 3.5 8.5 8.5L12 20.5 3.5 12z" />,

  exchange: <path d="M4 8h13l-3-3m6 11H7l3 3" />,
  regulator: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="12" cy="12" r="0.8" />
    </>
  ),
  police: (
    <>
      <path d="M12 3.5 19 6v6c0 4-3 7-7 8.5C8 19 5 16 5 12V6z" />
      <path d="m12 8 1.3 2.7 2.7.3-2 2 .5 2.9-2.5-1.4-2.5 1.4.5-2.9-2-2 2.7-.3z" />
    </>
  ),

  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  cross: <path d="M6 6l12 12M18 6 6 18" />,
  warning: <path d="M12 4.5 21 19.5H3zM12 10v4M12 17h.01" />,
  plus: <path d="M12 5.5v13M5.5 12h13" />,
  edit: <path d="M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17z" />,
  reviewed: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="m8.5 12 2.5 2.5 4.5-5" />
    </>
  ),

  zoomIn: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M11 8.5v5M8.5 11h5m2.5 5 4 4" />
    </>
  ),
  zoomOut: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M8.5 11h5m2.5 5 4 4" />
    </>
  ),
  fit: <path d="M4 9V5.5A1.5 1.5 0 0 1 5.5 4H9m6 0h3.5A1.5 1.5 0 0 1 20 5.5V9m0 6v3.5a1.5 1.5 0 0 1-1.5 1.5H15m-6 0H5.5A1.5 1.5 0 0 1 4 18.5V15" />,
  reset: <path d="M19.5 12a7.5 7.5 0 1 1-2.3-5.4M19.5 4v4h-4" />,
};

/**
 * `size` is a number of pixels rather than a class so an icon can sit inline
 * with text of any size. Decorative by default — pass a `label` only when the
 * icon is the sole carrier of meaning, which is rare here (nearly every icon in
 * this app sits beside its own text).
 */
export function Icon({
  name,
  size = 16,
  className,
  label,
}: {
  name: IconName;
  size?: number;
  className?: string;
  label?: string;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}
