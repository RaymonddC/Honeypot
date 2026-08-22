"use client";

/**
 * Users — access management for an agency (UAM).
 *
 * Replaces the old way of provisioning people: editing the
 * `ITTU_OAUTH_PROVISION` env allowlist and redeploying. An agency-admin manages
 * their own agency here; a platform-admin can act across agencies.
 *
 * **Client-side gating is UX, not security.** The nav entry and this page hide
 * themselves from non-admins, but the server is the real gate — every mutation
 * is role-checked there, and this page renders whatever 403 comes back rather
 * than assuming a hidden link protected anything.
 *
 * The guards are the substance of the feature (you cannot lock yourself out,
 * you cannot strand an agency with no admin, you cannot escalate to
 * platform-admin), so tripping one shows the RULE, not a generic error.
 */

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import {
  ROLES,
  UsersApiError,
  canAdminister,
  createUser,
  listUsers,
  updateUser,
  type AdminUser,
} from "@/lib/users/api";

const INPUT =
  "h-8 rounded-lg border border-line bg-elevated px-2.5 text-[11.5px] text-fg outline-none transition-colors placeholder:text-muted focus:border-accent/40";
const BTN =
  "h-8 shrink-0 rounded-lg border border-line bg-elevated px-3 text-[11px] font-semibold text-fg transition-colors hover:border-accent/40 disabled:opacity-50";

/** Plain-language labels — `bank-compliance` is a key, not a job title. */
const ROLE_LABEL: Record<string, string> = {
  "police-investigator": "Police investigator",
  "regulator-analyst": "Regulator analyst",
  "bank-compliance": "Bank compliance",
  "exchange-compliance": "Exchange compliance",
  "agency-admin": "Agency admin",
  "platform-admin": "Platform admin",
};

/**
 * Each guard explains the rule it enforced. These are deliberate safety rails,
 * and an admin who hits one should learn why it exists — otherwise a correct
 * refusal reads as a broken button.
 */
function explain(err: unknown): string {
  if (!(err instanceof UsersApiError)) {
    return err instanceof Error ? err.message : "Something went wrong.";
  }
  switch (err.code) {
    case "self_lockout":
      return "You can't deactivate or demote your own account — ask another admin to do it, so nobody locks themselves out.";
    case "last_admin":
      return "This is the agency's last active admin. Promote someone else first, or the agency would have nobody able to restore access.";
    case "privilege_escalation":
      return "Only a platform-admin can grant the platform-admin role.";
    case "cross_agency_forbidden":
      return "You can only administer your own agency's users.";
    case "user_exists":
      return err.message;
    case "account_deactivated":
      return "That account is deactivated.";
    default:
      return err.message;
  }
}

export default function UsersPage() {
  // The app's own auth context — no second round-trip just to learn the role.
  const { me } = useAuth();
  const [rows, setRows] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<string>("police-investigator");
  const [inviting, setInviting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await listUsers());
      setError(null);
    } catch (e) {
      setError(explain(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const isAdmin = canAdminister(me?.role);

  useEffect(() => {
    if (isAdmin) void load();
    else setLoading(false);
  }, [isAdmin, load]);

  const invite = async () => {
    setInviting(true);
    setNotice(null);
    try {
      const created = await createUser({
        email: email.trim(),
        name: name.trim(),
        role,
      });
      setEmail("");
      setName("");
      setError(null);
      setNotice(
        `${created.email} can now sign in with Google as ${ROLE_LABEL[created.role] ?? created.role}.`,
      );
      await load();
    } catch (e) {
      setError(explain(e));
    } finally {
      setInviting(false);
    }
  };

  const patch = async (u: AdminUser, change: { role?: string; is_active?: boolean }) => {
    setBusyId(u.id);
    setNotice(null);
    try {
      await updateUser(u.id, change);
      setError(null);
      if (change.is_active === false) {
        // Say what actually happens. Request auth is pure JWT and never reads
        // the database, so an already-issued token stays valid until it
        // expires — implying an instant lockout would be a lie.
        setNotice(
          `${u.email} can no longer sign in. An active session may persist until their token expires.`,
        );
      } else if (change.is_active === true) {
        setNotice(`${u.email} can sign in again.`);
      } else if (change.role) {
        setNotice(
          `${u.email} is now ${ROLE_LABEL[change.role] ?? change.role}. It applies the next time they sign in.`,
        );
      }
      await load();
    } catch (e) {
      setError(explain(e));
    } finally {
      setBusyId(null);
    }
  };

  if (!loading && !isAdmin) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-8">
        <h1 className="text-xl font-bold tracking-tight">Users</h1>
        <p className="mt-2 text-xs text-muted">
          Managing accounts needs an admin role. Ask your agency admin if you
          need access changed.
        </p>
      </div>
    );
  }

  const canSubmit = email.trim().length > 3 && name.trim().length > 0 && !inviting;

  return (
    <div className="mx-auto max-w-5xl px-4 py-5">
      <div className="mb-3.5">
        <h1 className="text-xl font-bold tracking-tight">Users</h1>
        <p className="mt-1 text-xs text-muted">
          Who can sign in to {me?.agency?.name ?? "your agency"}, and what they may do. Every change
          here is recorded in the{" "}
          <a href="/audit" className="text-accent-bright hover:underline">
            audit trail
          </a>
          . There are no passwords to manage — people sign in with Google, and
          access is decided by whether they appear on this list.
        </p>
      </div>

      {error && <p className="mb-3 text-[11px] text-risk-high">✗ {error}</p>}
      {notice && <p className="mb-3 text-[11px] text-accent-bright">✓ {notice}</p>}

      <div className="mb-3.5 rounded-card border border-line bg-card">
        <div className="border-b border-line px-3.5 py-2.5">
          <span className="eyebrow">Give someone access</span>
        </div>
        <div className="p-3.5">
          <div className="grid gap-2 sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)_auto]">
            <input
              type="email"
              value={email}
              placeholder="name@agency.go.id"
              spellCheck={false}
              onChange={(e) => setEmail(e.target.value)}
              className={INPUT}
              aria-label="Email address"
            />
            <input
              type="text"
              value={name}
              placeholder="Full name"
              onChange={(e) => setName(e.target.value)}
              className={INPUT}
              aria-label="Full name"
            />
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className={INPUT}
              aria-label="Role"
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r] ?? r}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => void invite()}
              disabled={!canSubmit}
              className={BTN}
            >
              {inviting ? "…" : "Add user"}
            </button>
          </div>
          <p className="mt-2 text-[10px] text-muted">
            The email must match the Google account they sign in with — it is the
            identity, not just a contact address.
          </p>
        </div>
      </div>

      <div className="rounded-card border border-line bg-card">
        <div className="border-b border-line px-3.5 py-2.5">
          <span className="eyebrow">People · {rows.length}</span>
        </div>
        <div className="p-2">
          {loading ? (
            <p className="px-1.5 py-2 text-[11px] text-muted">Loading…</p>
          ) : rows.length === 0 ? (
            <p className="px-1.5 py-3 text-[11px] text-muted">
              Nobody yet. Add the first person above — until then, only seeded
              demo accounts can sign in.
            </p>
          ) : (
            <ul className="space-y-1">
              {rows.map((u) => {
                const busy = busyId === u.id;
                return (
                  <li
                    key={u.id}
                    className="flex flex-wrap items-center gap-2 rounded-lg bg-elevated px-2.5 py-2 text-[11.5px]"
                  >
                    <span
                      className={`font-medium ${u.is_active ? "text-fg" : "text-muted line-through"}`}
                    >
                      {u.name}
                    </span>
                    <span className="font-mono text-[10.5px] text-muted">{u.email}</span>
                    {!u.is_active && (
                      <span className="rounded bg-risk-high/[.14] px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-wide text-risk-high">
                        deactivated
                      </span>
                    )}

                    <div className="ml-auto flex items-center gap-2">
                      <select
                        value={u.role}
                        disabled={busy}
                        onChange={(e) => void patch(u, { role: e.target.value })}
                        className={`${INPUT} h-7 disabled:opacity-50`}
                        aria-label={`Role for ${u.email}`}
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {ROLE_LABEL[r] ?? r}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void patch(u, { is_active: !u.is_active })}
                        title={
                          u.is_active
                            ? "Stop this account signing in"
                            : "Let this account sign in again"
                        }
                        className={`${BTN} h-7`}
                      >
                        {busy ? "…" : u.is_active ? "Deactivate" : "Reactivate"}
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
