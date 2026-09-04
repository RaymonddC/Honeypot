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
import { useTranslations } from "next-intl";
import { useAuth } from "@/components/auth/auth-provider";
import { roleLabel } from "@/lib/auth/types";
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

/**
 * Each guard explains the rule it enforced. These are deliberate safety rails,
 * and an admin who hits one should learn why it exists — otherwise a correct
 * refusal reads as a broken button.
 */
function explain(err: unknown, t: ReturnType<typeof useTranslations>): string {
  if (!(err instanceof UsersApiError)) {
    return err instanceof Error ? err.message : t("errors.generic");
  }
  switch (err.code) {
    case "self_lockout":
      return t("errors.selfLockout");
    case "last_admin":
      return t("errors.lastAdmin");
    case "privilege_escalation":
      return t("errors.privilegeEscalation");
    case "cross_agency_forbidden":
      return t("errors.crossAgencyForbidden");
    case "user_exists":
      return err.message;
    case "account_deactivated":
      return t("errors.accountDeactivated");
    default:
      return err.message;
  }
}

export default function UsersPage() {
  const t = useTranslations("users");
  const tRoles = useTranslations("roles");
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
      setError(explain(e, t));
    } finally {
      setLoading(false);
    }
  }, [t]);

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
        t("notices.invited", { email: created.email, role: roleLabel(created.role, tRoles) }),
      );
      await load();
    } catch (e) {
      setError(explain(e, t));
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
        setNotice(t("notices.deactivated", { email: u.email }));
      } else if (change.is_active === true) {
        setNotice(t("notices.reactivated", { email: u.email }));
      } else if (change.role) {
        setNotice(
          t("notices.roleChanged", { email: u.email, role: roleLabel(change.role, tRoles) }),
        );
      }
      await load();
    } catch (e) {
      setError(explain(e, t));
    } finally {
      setBusyId(null);
    }
  };

  if (!loading && !isAdmin) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-8">
        <h1 className="text-xl font-bold tracking-tight">{t("title")}</h1>
        <p className="mt-2 text-xs text-muted">
          {t("gateBody")}
        </p>
      </div>
    );
  }

  const canSubmit = email.trim().length > 3 && name.trim().length > 0 && !inviting;

  return (
    <div className="mx-auto max-w-5xl px-4 py-5">
      <div className="mb-3.5">
        <h1 className="text-xl font-bold tracking-tight">{t("title")}</h1>
        <p className="mt-1 text-xs text-muted">
          {/* `auditLink` is a TAG in the message (<auditLink>…</auditLink>),
              so it takes a function receiving the tag's chunks. It was written
              as a value placeholder ({auditLink}) with a function passed here,
              and React then tried to render the function itself: "Functions are
              not valid as a React child". The link text lives inside the tag in
              each locale, so it stays translatable. */}
          {t.rich("subtitle", {
            agency: me?.agency?.name ?? t("agencyFallback"),
            auditLink: (chunks) => (
              <a href="/audit" className="text-accent-bright hover:underline">
                {chunks}
              </a>
            ),
          })}
        </p>
      </div>

      {error && <p className="mb-3 text-[11px] text-risk-high">✗ {error}</p>}
      {notice && <p className="mb-3 text-[11px] text-accent-bright">✓ {notice}</p>}

      <div className="mb-3.5 rounded-card border border-line bg-card">
        <div className="border-b border-line px-3.5 py-2.5">
          <span className="eyebrow">{t("giveAccessEyebrow")}</span>
        </div>
        <div className="p-3.5">
          <div className="grid gap-2 sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)_auto]">
            <input
              type="email"
              value={email}
              placeholder={t("emailPlaceholder")}
              spellCheck={false}
              onChange={(e) => setEmail(e.target.value)}
              className={INPUT}
              aria-label={t("emailAriaLabel")}
            />
            <input
              type="text"
              value={name}
              placeholder={t("namePlaceholder")}
              onChange={(e) => setName(e.target.value)}
              className={INPUT}
              aria-label={t("nameAriaLabel")}
            />
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className={INPUT}
              aria-label={t("roleAriaLabel")}
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {roleLabel(r, tRoles)}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => void invite()}
              disabled={!canSubmit}
              className={BTN}
            >
              {inviting ? t("addUserBusy") : t("addUser")}
            </button>
          </div>
          <p className="mt-2 text-[10px] text-muted">
            {t("emailHint")}
          </p>
        </div>
      </div>

      <div className="rounded-card border border-line bg-card">
        <div className="border-b border-line px-3.5 py-2.5">
          <span className="eyebrow">{t("peopleEyebrow", { count: rows.length })}</span>
        </div>
        <div className="p-2">
          {loading ? (
            <p className="px-1.5 py-2 text-[11px] text-muted">{t("loading")}</p>
          ) : rows.length === 0 ? (
            <p className="px-1.5 py-3 text-[11px] text-muted">
              {t("emptyState")}
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
                        {t("deactivatedChip")}
                      </span>
                    )}

                    <div className="ml-auto flex items-center gap-2">
                      <select
                        value={u.role}
                        disabled={busy}
                        onChange={(e) => void patch(u, { role: e.target.value })}
                        className={`${INPUT} h-7 disabled:opacity-50`}
                        aria-label={t("roleForUser", { email: u.email })}
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {roleLabel(r, tRoles)}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void patch(u, { is_active: !u.is_active })}
                        title={
                          u.is_active
                            ? t("stopSignIn")
                            : t("allowSignIn")
                        }
                        className={`${BTN} h-7`}
                      >
                        {busy ? t("actionBusy") : u.is_active ? t("deactivate") : t("reactivate")}
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
