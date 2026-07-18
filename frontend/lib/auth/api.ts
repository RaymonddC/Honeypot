/**
 * Auth API client (P5):
 *
 *   POST /api/auth/login   {agency_id, role}  → {jwt|access_token|token, user?}   (POC demo login)
 *   POST /api/auth/google  {id_token}         → {jwt, user}                        (LIVE — stub here)
 *   GET  /api/auth/me                          → {user, agency, role}
 *   GET  /api/config                           → effective POC/LIVE mode (+ per-module)
 *
 * All responses are normalized defensively (same `first(...)` pattern as the
 * other lib/<mod>/api.ts clients) so minor backend field renames don't break
 * the shell. /api/config falls back to NEXT_PUBLIC_ITTU_MODE when offline so
 * the badge still renders in a static demo.
 */

import { apiFetch } from "@/lib/http";
import type {
  AppConfig,
  AuthAgency,
  AuthMe,
  AuthUser,
  Mode,
  ModuleMode,
} from "./types";
import { AGENCIES, roleLabel } from "./types";

/* eslint-disable @typescript-eslint/no-explicit-any */

const first = (...vals: unknown[]): any =>
  vals.find((v) => v !== undefined && v !== null);

const str = (v: unknown): string | undefined =>
  v == null ? undefined : String(v);

async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = 6000,
): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await apiFetch(path, { ...init, signal: ctrl.signal });
    if (!res.ok) {
      let detail = "";
      try {
        const body = await res.json();
        detail = str(
          first(body?.error?.message, body?.detail, body?.message),
        ) ?? "";
      } catch {
        /* non-JSON error body */
      }
      throw new Error(detail || `HTTP ${res.status}`);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

/* ── Normalizers ───────────────────────────────────────────────────────── */

function normalizeUser(raw: any, fallbackName?: string): AuthUser {
  const u = first(raw?.user, raw) ?? {};
  return {
    id: str(first(u?.id, u?.sub, u?.user_id)) ?? "unknown",
    name:
      str(first(u?.name, u?.full_name, u?.display_name, u?.email)) ??
      fallbackName ??
      "Analyst",
    email: str(u?.email),
  };
}

function normalizeAgency(raw: any): AuthAgency {
  const a = first(raw?.agency, raw) ?? {};
  const id = str(first(a?.id, a?.agency_id, a?.slug)) ?? "unknown";
  const known = AGENCIES.find((k) => k.id === id);
  return {
    id,
    name: str(first(a?.name, a?.display_name)) ?? known?.name ?? id,
    type: str(first(a?.type, a?.agency_type, a?.kind)),
  };
}

function normalizeMe(raw: any): AuthMe {
  const role =
    str(first(raw?.role, raw?.user?.role, raw?.user?.roles?.[0])) ?? "analyst";
  return {
    user: normalizeUser(raw, roleLabel(role)),
    agency: normalizeAgency(raw),
    role,
  };
}

export const asMode = (v: unknown): Mode =>
  String(v ?? "").toLowerCase() === "live" ? "LIVE" : "POC";

export function normalizeModules(raw: any): ModuleMode[] {
  const mods = first(raw?.modules, raw?.module_modes, raw?.per_module);
  if (Array.isArray(mods)) {
    return mods.map((m: any) => ({
      module: str(first(m?.module, m?.name, m?.id)) ?? "?",
      mode: asMode(first(m?.mode, m?.effective_mode)),
      adapters: m?.adapters ?? undefined,
    }));
  }
  if (mods && typeof mods === "object") {
    return Object.entries(mods).map(([module, v]: [string, any]) => ({
      module,
      mode: asMode(typeof v === "object" ? first(v?.mode, v?.effective_mode) : v),
      adapters: typeof v === "object" ? (v?.adapters ?? undefined) : undefined,
    }));
  }
  return [];
}

/* ── Public surface ────────────────────────────────────────────────────── */

/**
 * Locally minted, unsigned session token for the offline demo path (backend
 * unreachable at login). Same claim shape as the real JWT so the shell renders
 * identically; a live backend will 401 it → automatic bounce back to /login.
 */
export function mintOfflineToken(agencyId: string, role: string): string {
  const b64 = (o: object) =>
    btoa(JSON.stringify(o))
      .replace(/=+$/, "")
      .replace(/\+/g, "-")
      .replace(/\//g, "_");
  const exp = Math.floor(Date.now() / 1000) + 8 * 3600;
  return `${b64({ alg: "none", typ: "JWT" })}.${b64({
    sub: "offline-demo",
    agency_id: agencyId,
    role,
    exp,
    offline: true,
  })}.offline`;
}

/** POC demo login → JWT string. Throws with a readable message on failure. */
export async function demoLogin(
  agencyId: string,
  role: string,
): Promise<{ jwt: string; me: AuthMe | null }> {
  const raw = await request<any>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agency_id: agencyId, role }),
  });
  const jwt = str(first(raw?.jwt, raw?.access_token, raw?.token));
  if (!jwt) throw new Error("login response carried no token");
  const me =
    raw?.user || raw?.agency ? normalizeMe({ ...raw, role: first(raw?.role, role) }) : null;
  return { jwt, me };
}

/**
 * LIVE login: exchange a Google Identity Services `id_token` for our JWT via
 * POST /api/auth/google. Same response shape as demoLogin ({token, user,
 * agency, role}); the readable backend error (`user_not_provisioned`,
 * `google_login_disabled`, …) surfaces via `request`'s thrown message.
 */
export async function googleLogin(
  idToken: string,
): Promise<{ jwt: string; me: AuthMe | null }> {
  const raw = await request<any>("/auth/google", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id_token: idToken }),
  });
  const jwt = str(first(raw?.jwt, raw?.access_token, raw?.token));
  if (!jwt) throw new Error("login response carried no token");
  const me = raw?.user || raw?.agency ? normalizeMe(raw) : null;
  return { jwt, me };
}

/** GET /api/auth/me — requires the Bearer token to already be stored. */
export async function fetchMe(): Promise<AuthMe> {
  const raw = await request<any>("/auth/me");
  return normalizeMe(first(raw?.data, raw));
}

/**
 * GET /api/config — real POC/LIVE mode per deployment.
 * Falls back to NEXT_PUBLIC_ITTU_MODE (source: "env") when unreachable.
 */
export async function fetchConfig(): Promise<AppConfig> {
  try {
    const raw = await request<any>("/config", undefined, 4000);
    const c = first(raw?.config, raw?.data, raw) ?? {};
    const modules = normalizeModules(c);
    const mode = asMode(
      first(
        c?.mode,
        c?.effective_mode,
        c?.global_mode,
        c?.data_mode,
        modules.some((m) => m.mode === "LIVE") ? "live" : "poc",
      ),
    );
    return { mode, modules, source: "api" };
  } catch {
    return {
      mode: asMode(process.env.NEXT_PUBLIC_ITTU_MODE ?? "poc"),
      modules: [],
      source: "env",
    };
  }
}
