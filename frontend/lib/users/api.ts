/**
 * User access management (UAM) client — `/api/users`.
 *
 * Unlike the other API modules this one preserves the server's error **code**,
 * not just its message. The UAM guards are the interesting part of the feature
 * (`last_admin`, `self_lockout`, `privilege_escalation`,
 * `cross_agency_forbidden`), and an admin who trips one deserves to be told
 * which rule stopped them and why — a generic "request failed" turns a
 * deliberate safety rail into an apparent bug.
 */

import { apiFetch } from "@/lib/http";

export interface AdminUser {
  id: string;
  agency_id: string;
  email: string;
  name: string;
  role: string;
  is_active: boolean;
}

/** The RBAC roles, mirroring backend `ROLES`. */
export const ROLES = [
  "police-investigator",
  "regulator-analyst",
  "bank-compliance",
  "exchange-compliance",
  "agency-admin",
  "platform-admin",
] as const;

export const ADMIN_ROLES: readonly string[] = ["agency-admin", "platform-admin"];

/** True when this role may open the Users screen at all. */
export const canAdminister = (role: string | undefined | null): boolean =>
  !!role && ADMIN_ROLES.includes(role);

/** An API failure that kept the server's machine-readable `code`. */
export class UsersApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "UsersApiError";
  }
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init);
  if (!res.ok) {
    let code = `http_${res.status}`;
    let message = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      message = body?.error?.message ?? message;
      code = body?.error?.code ?? code;
    } catch {
      /* non-JSON error body — keep the status-derived defaults */
    }
    throw new UsersApiError(message, code, res.status);
  }
  return (await res.json()) as T;
}

const body = (payload: unknown): RequestInit => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
});

/** Users this admin may see. platform-admin can pass another agency's id. */
export function listUsers(agencyId?: string) {
  const qs = agencyId ? `?agency_id=${encodeURIComponent(agencyId)}` : "";
  return json<AdminUser[]>(`/users${qs}`);
}

export function createUser(input: {
  email: string;
  name: string;
  role: string;
  agency_id?: string;
}) {
  return json<AdminUser>("/users", { method: "POST", ...body(input) });
}

/** Send only what is changing — the API rejects an empty patch. */
export function updateUser(
  id: string,
  patch: { role?: string; is_active?: boolean },
) {
  return json<AdminUser>(`/users/${encodeURIComponent(id)}`, {
    method: "PATCH",
    ...body(patch),
  });
}
