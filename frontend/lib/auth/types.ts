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
}

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

export const roleLabel = (role: string): string =>
  ROLE_LABELS[role] ??
  role.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());

/** "Bareskrim Polri" → "BP", "Analyst" → "AN". */
export function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "??";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
