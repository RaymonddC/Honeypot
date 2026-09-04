/**
 * Role administration client — `/api/roles` and `/api/capabilities`.
 *
 * Like the UAM client, this preserves the server's error **code**. The guards
 * are the feature here: an administrator who is stopped from removing the last
 * `users.admin` must be told which rule caught them and why, or a deliberate
 * safety rail reads as a bug.
 *
 * The capability LIST comes from the server rather than being duplicated here.
 * Hardcoding it would let this file drift into offering switches the backend
 * does not enforce — the exact failure the closed capability set exists to
 * prevent.
 */

import { apiFetch } from "@/lib/http";

// Paths below are RELATIVE to apiFetch's `${API_BASE}/api` prefix — passing
// "/api/roles" here produces "/api/api/roles" and a 404 that looks like a
// missing route rather than a doubled prefix.

export interface Role {
  name: string;
  capabilities: string[];
  user_count: number;
  /** Built-in roles are referenced by NAME in the seed migration, the OAuth
   *  allowlist and the demo login, so they cannot be deleted. */
  builtin: boolean;
}

export interface Capability {
  key: string;
  label: string;
  /** Written for the person deciding whether to grant it. Shown in full. */
  description: string;
}

/** An API failure that kept the server's machine-readable `code`. */
export class RolesApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "RolesApiError";
  }
}

async function json<T>(path: string, init?: RequestInit): Promise<T | null> {
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
    throw new RolesApiError(message, code, res.status);
  }
  // DELETE answers 204 with no body.
  if (res.status === 204) return null;
  return (await res.json()) as T;
}

export const listRoles = () => json<Role[]>("/roles") as Promise<Role[]>;

export const listCapabilities = () =>
  json<Capability[]>("/capabilities") as Promise<Capability[]>;

export const createRole = (name: string, capabilities: string[]) =>
  json<Role>("/roles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, capabilities }),
  }) as Promise<Role>;

export const setRoleCapabilities = (name: string, capabilities: string[]) =>
  json<Role>(`/roles/${encodeURIComponent(name)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ capabilities }),
  }) as Promise<Role>;

export const deleteRole = (name: string) =>
  json<null>(`/roles/${encodeURIComponent(name)}`, { method: "DELETE" });
