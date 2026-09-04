/** Auth & identity types (P5) — see docs/API-Contract.md + Security-Evidence.md. */

export interface AuthUser {
  id: string;
  name: string;
  email?: string;
}

export interface AuthAgency {
  id: string;
  name: string;
  type?: string;
}

/** GET /api/auth/me → normalized. */
export interface AuthMe {
  user: AuthUser;
  agency: AuthAgency;
  role: string;
  /** What this role may DO, from GET /api/auth/me.
   *
   *  Used to decide what the UI offers — never as the authorisation decision,
   *  which the server makes on every request. Gating a menu on a hardcoded list
   *  of role NAMES is the coupling capabilities exist to remove: a role created
   *  in Roles administration would be invisible to the menu forever.
   *
   *  Empty when derived from JWT claims alone (offline/optimistic boot), so a
   *  check must treat "absent" as "not permitted" rather than "unknown". */
  capabilities?: string[];
}

/** Capability keys, mirroring app/core/capabilities.py. */
export const CAP = {
  honeypotRead: "honeypot.read",
  honeypotEngage: "honeypot.engage",
  honeypotDial: "honeypot.dial",
  caseWrite: "case.write",
  actionGenerate: "action.generate",
  dispatchSend: "dispatch.send",
  usersAdmin: "users.admin",
  rolesAdmin: "roles.admin",
} as const;

/** Roles that held each capability BEFORE capabilities existed.
 *
 *  A compatibility shim, and it earns its keep: the frontend and backend deploy
 *  independently (Vercel / Render), so a frontend that ships first would ask an
 *  older `/api/auth/me` for a field it does not return. Failing closed on that
 *  would silently remove Users and Roles from every administrator's menu — an
 *  outage caused purely by deploy ORDER, with nothing in the logs.
 *
 *  Delete this once the backend carrying `capabilities` is everywhere. */
const LEGACY_ROLE_CAPABILITIES: Record<string, string[]> = {
  "police-investigator": [
    "honeypot.read",
    "honeypot.engage",
    "honeypot.dial",
    "case.write",
    "action.generate",
    "dispatch.send",
  ],
  "regulator-analyst": ["case.write", "action.generate", "dispatch.send"],
  "bank-compliance": ["action.generate"],
  "exchange-compliance": ["action.generate"],
  "agency-admin": [
    "honeypot.read",
    "honeypot.engage",
    "honeypot.dial",
    "case.write",
    "action.generate",
    "dispatch.send",
    "users.admin",
  ],
  "platform-admin": [
    "honeypot.read",
    "honeypot.engage",
    "honeypot.dial",
    "case.write",
    "action.generate",
    "dispatch.send",
    "users.admin",
    "roles.admin",
  ],
};

/** Whether `me` may do `capability`.
 *
 *  NEVER the authorisation decision — the server re-checks on every request and
 *  each page renders whatever 403 comes back. This only decides whether to
 *  offer a door.
 *
 *  Absent `capabilities` means the server did not send them: either an older
 *  backend, or the optimistic boot from JWT claims alone. Both fall back to the
 *  legacy role map rather than to "no", because a wrongly-shown link costs a
 *  403, while a wrongly-hidden one costs an administrator their way in. */
export const can = (me: AuthMe | null, capability: string): boolean => {
  if (!me) return false;
  if (me.capabilities) return me.capabilities.includes(capability);
  return (LEGACY_ROLE_CAPABILITIES[me.role] ?? []).includes(capability);
};

export type Mode = "POC" | "LIVE";

export interface ModuleMode {
  module: string;
  mode: Mode;
  adapters?: Record<string, string>;
}

/** GET /api/config → normalized. `source` mirrors the module screens' badge. */
export interface AppConfig {
  mode: Mode;
  modules: ModuleMode[];
  source: "api" | "env";
}

/* ── Demo login catalogue (POC) ────────────────────────────────────────── */

export interface AgencyOption {
  /** Seed slug sent as `agency_id` to POST /api/auth/login. */
  id: string;
  name: string;
  /** Small descriptor under the name. */
  sub: string;
  /** Two-letter mark for the tile. */
  mark: string;
  /** RBAC roles this agency can assume (Security-Evidence §1). */
  roles: string[];
}

// English fallback only — used when no translator is passed (e.g. non-React
// call sites) or the role isn't a known key. The real, localized labels live
// in messages/{locale}.json under "roles.*"; components should call
// `roleLabel(role, t)` with `t = useTranslations("roles")` so the label
// follows the active locale. See components/auth/login-form.tsx for the
// reference usage.
export const ROLE_LABELS: Record<string, string> = {
  "police-investigator": "Police investigator",
  "regulator-analyst": "Regulator analyst",
  "bank-compliance": "Bank compliance",
  "exchange-compliance": "Exchange compliance",
  "agency-admin": "Agency admin",
  "platform-admin": "Platform admin",
};

export const AGENCIES: AgencyOption[] = [
  {
    id: "bareskrim",
    name: "Bareskrim Polri",
    sub: "Dittipidsiber · law enforcement",
    mark: "BR",
    roles: ["police-investigator", "agency-admin"],
  },
  {
    id: "ppatk",
    name: "PPATK",
    sub: "Financial intelligence unit",
    mark: "PP",
    roles: ["regulator-analyst", "agency-admin"],
  },
  {
    id: "ojk",
    name: "OJK",
    sub: "Financial services authority",
    mark: "OJ",
    roles: ["regulator-analyst", "agency-admin"],
  },
  {
    id: "bank-bca",
    name: "Bank BCA",
    sub: "Commercial bank · AML desk",
    mark: "BC",
    roles: ["bank-compliance", "agency-admin"],
  },
  {
    id: "indodax",
    name: "Indodax",
    sub: "Crypto exchange · compliance",
    mark: "IX",
    roles: ["exchange-compliance", "agency-admin"],
  },
];

/**
 * `t` is `useTranslations("roles")` from next-intl. Falls back to the
 * English static map (then a humanized slug) when no translator is given or
 * the role has no message key, so existing non-component callers still work.
 */
export const roleLabel = (
  role: string,
  t?: (key: string) => string,
): string => {
  if (t) {
    try {
      return t(role);
    } catch {
      // no message for this role key — fall through to the static map
    }
  }
  return (
    ROLE_LABELS[role] ??
    role.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase())
  );
};

/**
 * Roles allowed to dispatch outward actions (freeze requests, STR filings) —
 * mirrors the backend's DISPATCH_ROLES (app/core/auth.py). Bank / exchange
 * compliance can generate & review but not dispatch: they RECEIVE the requests.
 */
export const DISPATCH_ROLES = new Set([
  "regulator-analyst",
  "police-investigator",
  "agency-admin",
  "platform-admin",
]);

export const canDispatch = (role: string): boolean => DISPATCH_ROLES.has(role);

/** "Bareskrim Polri" → "BP", "Analyst" → "AN". */
export function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "??";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
