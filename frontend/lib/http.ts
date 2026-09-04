/**
 * Shared HTTP helper — single place where the API base URL, the JWT and the
 * `Authorization: Bearer <jwt>` header live. Every lib/<mod>/api.ts routes
 * its fetches through `apiFetch` so protected endpoints automatically carry
 * the token once the analyst logs in (P5 auth).
 *
 * Token storage: localStorage (`ittu.jwt`) — acceptable for the POC demo
 * login; LIVE will move to an httpOnly cookie minted by the backend.
 */

export const API_BASE = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

const TOKEN_KEY = "ittu.jwt";

/** Fired on window whenever a request comes back 401 (token expired/revoked). */
export const UNAUTHORIZED_EVENT = "ittu:unauthorized";

/* ── Token storage ─────────────────────────────────────────────────────── */

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(jwt: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(TOKEN_KEY, jwt);
  } catch {
    /* storage unavailable (private mode) — session still works in-memory */
  }
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

/* ── Why the session ended ─────────────────────────────────────────────────
 * An involuntary logout (a 401, or an already-expired token found at boot)
 * and a deliberate "sign out" both land on /login, and from the operator's
 * side they look identical: the screen just changed. With a 1h TTL and no
 * refresh flow that bounce is routine, so the reason is handed to /login
 * rather than left as a mystery. sessionStorage, not the URL: it survives the
 * redirect, is read exactly once, and doesn't leave a stale "?expired" behind
 * on a bookmarked login. */

const LOGOUT_REASON_KEY = "ittu.logout-reason";

export type LogoutReason = "expired";

export function setLogoutReason(reason: LogoutReason): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(LOGOUT_REASON_KEY, reason);
  } catch {
    /* storage unavailable — the notice is a courtesy, never a blocker */
  }
}

/** Read the pending reason and clear it, so it shows once and not again. */
export function takeLogoutReason(): LogoutReason | null {
  if (typeof window === "undefined") return null;
  try {
    const v = window.sessionStorage.getItem(LOGOUT_REASON_KEY);
    if (v) window.sessionStorage.removeItem(LOGOUT_REASON_KEY);
    return v === "expired" ? v : null;
  } catch {
    return null;
  }
}

/** Decode a JWT payload without verifying (client-side convenience only). */
export function tokenPayload(jwt: string): {
  sub?: string;
  agency_id?: string;
  role?: string;
  exp?: number;
  [k: string]: unknown;
} | null {
  try {
    const part = jwt.split(".")[1];
    if (!part) return null;
    const b64 = part.replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(b64));
  } catch {
    return null;
  }
}

/** True when the token exists and is not past its `exp` claim. */
export function tokenLooksValid(jwt: string | null): boolean {
  if (!jwt) return false;
  const payload = tokenPayload(jwt);
  if (!payload) return false;
  if (typeof payload.exp === "number")
    return payload.exp * 1000 > Date.now() + 5_000;
  return true; // no exp claim — let the server decide
}

/* ── Fetch ─────────────────────────────────────────────────────────────── */

/**
 * fetch() against the backend with the Bearer token attached.
 * `path` starting with "/" is resolved against `${API_BASE}/api`;
 * absolute URLs pass through untouched.
 */
export async function apiFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const url = /^https?:\/\//.test(path) ? path : `${API_BASE}/api${path}`;
  const headers = new Headers(init?.headers);
  const token = getToken();
  if (token && !headers.has("Authorization"))
    headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(url, { ...init, headers });

  if (res.status === 401 && typeof window !== "undefined" && token) {
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
  }
  return res;
}
