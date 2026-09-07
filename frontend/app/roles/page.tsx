"use client";

/**
 * Roles administration — what each role may do.
 *
 * The screen exists because roles are DATA (`core.roles`), not a list frozen in
 * code. Two things it must not do, both learned the hard way in this codebase:
 *
 *  • It must never offer a capability the backend does not enforce. The list is
 *    fetched from `/api/capabilities` rather than duplicated here, so a switch
 *    can only exist if something checks it.
 *  • It must never imply a change took effect when a guard refused it. Every
 *    refusal is shown with the server's own explanation, not a generic error —
 *    the guards are the feature, and "nothing happened" reads as a bug.
 *
 * Gated on the `roles.admin` CAPABILITY rather than a role name: gating on names
 * is the coupling this whole system removes, and a role created here would
 * otherwise be invisible to its own screen.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { useAuth } from "@/components/auth/auth-provider";
import { CAP, can } from "@/lib/auth/types";
import {
  type Capability,
  type CapabilityGroup,
  type Role,
  RolesApiError,
  createRole,
  deleteRole,
  listCapabilities,
  listRoles,
  setRoleCapabilities,
} from "@/lib/roles/api";
import { Icon } from "@/components/icon";

function explain(err: unknown, t: ReturnType<typeof useTranslations>): string {
  if (!(err instanceof RolesApiError)) {
    return err instanceof Error ? err.message : t("errors.generic");
  }
  // The server's messages for these already say what to do next, so they are
  // shown verbatim rather than replaced with a shorter, vaguer translation.
  switch (err.code) {
    case "last_holder":
    case "role_in_use":
    case "builtin_role":
    case "unknown_capability":
    case "role_exists":
      return err.message;
    case "missing_capability":
      return t("errors.missingCapability");
    default:
      return err.message;
  }
}

export default function RolesPage() {
  // Namespace is `rolesAdmin`, NOT `roles`: the `roles` namespace holds role
  // LABELS keyed by role name, so a role someone names "page" or "title" would
  // collide with this screen's copy.
  const t = useTranslations("rolesAdmin");
  const { me } = useAuth();
  const isAdmin = can(me, CAP.rolesAdmin);

  const [roles, setRoles] = useState<Role[]>([]);
  const [groups, setGroups] = useState<CapabilityGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [newName, setNewName] = useState("");

  const load = useCallback(async () => {
    const [r, g] = await Promise.all([listRoles(), listCapabilities()]);
    setRoles(r);
    setGroups(g);
  }, []);

  useEffect(() => {
    if (!isAdmin) {
      setLoading(false);
      return;
    }
    void load()
      .catch((e) => setError(explain(e, t)))
      .finally(() => setLoading(false));
  }, [isAdmin, load, t]);

  const toggle = async (role: Role, key: string, on: boolean) => {
    setError(null);
    setNotice(null);
    setBusy(role.name);
    const next = on
      ? [...role.capabilities, key]
      : role.capabilities.filter((c) => c !== key);
    try {
      await setRoleCapabilities(role.name, next);
      await load();
      setNotice(
        on
          ? t("notices.granted", { capability: key, role: role.name })
          : t("notices.revoked", { capability: key, role: role.name }),
      );
    } catch (e) {
      // Reload on failure too: the guard refused, so the server's state is
      // authoritative and the checkbox must snap back rather than sit showing
      // a change that did not happen.
      setError(explain(e, t));
      await load().catch(() => undefined);
    } finally {
      setBusy(null);
    }
  };

  const create = async () => {
    const name = newName.trim().toLowerCase();
    if (!name) return;
    setError(null);
    setNotice(null);
    setBusy("__new__");
    try {
      await createRole(name, []);
      setNewName("");
      await load();
      setNotice(t("notices.created", { role: name }));
    } catch (e) {
      setError(explain(e, t));
    } finally {
      setBusy(null);
    }
  };

  const remove = async (role: Role) => {
    setError(null);
    setNotice(null);
    setBusy(role.name);
    try {
      await deleteRole(role.name);
      await load();
      setNotice(t("notices.deleted", { role: role.name }));
    } catch (e) {
      setError(explain(e, t));
    } finally {
      setBusy(null);
    }
  };

  // Flattened once for the summary chips and label lookup — the GROUPS drive
  // the expanded form, this drives the closed one.
  const caps = useMemo<Capability[]>(
    () => groups.flatMap((g) => g?.capabilities ?? []),
    [groups],
  );
  const byKey = useMemo(
    () => Object.fromEntries(caps.map((c) => [c.key, c])),
    [caps],
  );

  if (!loading && !isAdmin) {
    return (
      <div className="mx-auto max-w-[560px] pt-10 text-center">
        <span
          className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-accent/10 text-2xl text-accent-bright"
          aria-hidden
        >
          <Icon name="roles" size={16} />
        </span>
        <h1 className="text-xl font-bold tracking-tight">{t("gateTitle")}</h1>
        <p className="mx-auto mt-1.5 max-w-[46ch] text-[13px] leading-relaxed text-muted">
          {t("gateBody")}
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-5">
      <div className="mb-4">
        <h1 className="text-2xl font-bold tracking-tight">{t("title")}</h1>
        <p className="mt-1.5 max-w-[64ch] text-[13px] leading-relaxed text-muted">{t("pageLead")}</p>
        <p className="mt-1 max-w-[64ch] text-[12px] leading-relaxed text-muted">{t("subtitle")}</p>
      </div>

      {error && (
        <p role="alert" className="mb-3 text-[12px] leading-relaxed text-risk-high">
          <Icon name="cross" size={11} className="mr-1 inline-block align-[-1px]" />{error}
        </p>
      )}
      {notice && (
        <p role="status" className="mb-3 text-[12px] text-accent-bright">
          <Icon name="check" size={11} className="mr-1 inline-block align-[-1px]" />{notice}
        </p>
      )}

      {/* Create */}
      <div className="mb-3.5 rounded-card border border-line bg-card">
        <div className="border-b border-line px-3.5 py-2.5">
          <span className="eyebrow">{t("createEyebrow")}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2 px-3.5 py-3">
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={t("namePlaceholder")}
            className="min-w-[220px] flex-1 rounded-md border border-line bg-elevated px-2.5 py-1.5 text-[12px] text-fg outline-none placeholder:text-muted focus:border-fg/20"
          />
          <button
            type="button"
            onClick={create}
            disabled={!newName.trim() || busy === "__new__"}
            className="cursor-pointer rounded-full border border-accent/40 bg-accent/10 px-3 py-1.5 text-[12px] text-accent-bright transition-colors hover:bg-accent/15 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy === "__new__" ? t("creating") : t("create")}
          </button>
        </div>
        <p className="border-t border-line px-3.5 py-2 text-[12px] leading-relaxed text-muted">
          {t("createHint")}
        </p>
      </div>

      {loading && <p className="text-[12px] text-muted">{t("loading")}</p>}

      {/* One collapsible card per role.
       *
       *  Native <details>, not React state: nine capabilities across six roles
       *  is far too much to render open, but the SUMMARY has to stay useful on
       *  its own — an administrator asking "what can a bank compliance officer
       *  do" should get the answer without opening anything. So the closed row
       *  lists the granted capabilities by name, and expanding is for CHANGING
       *  them, not for reading them.
       *
       *  <details> also gets keyboard operation and open-state announcement for
       *  free, which a div-and-useState version has to reimplement and usually
       *  doesn't. */}
      <div className="space-y-2">
        {roles.map((role) => {
          const granted = caps.filter((c) => role.capabilities.includes(c.key));
          return (
            <details
              key={role.name}
              className="group overflow-hidden rounded-card border border-line bg-card"
            >
              <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-2 gap-y-1 px-3.5 py-2.5 transition-colors hover:bg-elevated/40 [&::-webkit-details-marker]:hidden">
                <span
                  className="w-3 flex-none text-[12px] text-muted transition-transform group-open:rotate-90"
                  aria-hidden
                >
                  <Icon name="dispatch" size={11} className="transition-transform group-open:rotate-90" />
                </span>
                <span className="text-sm font-medium text-fg">{role.name}</span>
                {role.builtin && (
                  <span className="rounded border border-line px-1.5 py-0.5 text-[12px] text-muted">
                    {t("builtin")}
                  </span>
                )}
                <span className="text-[12px] text-muted">
                  {t("userCount", { count: role.user_count })}
                </span>

                {/* The policy at a glance. `no access` is a real, common state
                    (a role someone just created) and must read as deliberate
                    rather than as a rendering failure. */}
                <span className="ml-auto flex flex-wrap items-center justify-end gap-1">
                  {granted.length === 0 ? (
                    <span className="text-[12px] italic text-muted">
                      {t("noAccess")}
                    </span>
                  ) : (
                    granted.map((c) => (
                      <span
                        key={c.key}
                        className="rounded border border-accent/25 bg-accent/[.07] px-1.5 py-0.5 text-[12px] text-accent-bright"
                      >
                        {c.label}
                      </span>
                    ))
                  )}
                </span>
              </summary>

              <div className="border-t border-line">
                {/* Sections, in the server's order. Grouping is presentation
                    only — a capability is defined by the consequence it
                    authorises, not by the screen it appears on — but nine
                    switches in one flat list is already hard to scan. */}
                {groups.map((group) => (
                  <div key={group.key}>
                    <div className="border-b border-line bg-elevated/30 px-3.5 py-1.5">
                      <span className="eyebrow">{group.label}</span>
                    </div>
                    <div className="divide-y divide-line">
                      {group.capabilities.map((cap) => {
                        const on = role.capabilities.includes(cap.key);
                        return (
                          <label
                            key={cap.key}
                            className="flex cursor-pointer items-start gap-2.5 px-3.5 py-2.5 transition-colors hover:bg-elevated/40"
                          >
                            <input
                              type="checkbox"
                              checked={on}
                              disabled={busy === role.name}
                              onChange={(e) => toggle(role, cap.key, e.target.checked)}
                              className="mt-0.5 h-3.5 w-3.5 flex-none accent-[var(--accent)]"
                            />
                            <span className="min-w-0">
                              <span className="flex flex-wrap items-center gap-1.5">
                                <span className="text-[12px] text-fg">{cap.label}</span>
                                {/* The raw key stays visible — audits and support
                                    tickets reference it directly — but as a small
                                    muted gloss next to the plain-language
                                    label, not the only thing shown. */}
                                <span
                                  title={t("capabilityKeyLabel")}
                                  className="rounded border border-line bg-elevated px-1 py-px text-[12px] text-muted"
                                >
                                  {cap.key}
                                </span>
                              </span>
                              {/* The description is the whole point of the row:
                                  it is written for the person deciding whether
                                  to grant this, so it is never truncated behind
                                  a tooltip. */}
                              <span className="mt-0.5 block text-[12px] leading-relaxed text-muted">
                                {cap.description}
                              </span>
                            </span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                ))}
                {!role.builtin && (
                  <div className="border-t border-line px-3.5 py-2.5">
                    <button
                      type="button"
                      onClick={() => remove(role)}
                      disabled={busy === role.name}
                      className="cursor-pointer rounded-md border border-line px-2.5 py-1 text-[12px] text-muted transition-colors hover:border-risk-high/40 hover:text-risk-high disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {t("delete")}
                    </button>
                  </div>
                )}
              </div>
            </details>
          );
        })}
      </div>

      <p className="mt-3.5 text-[12px] leading-relaxed text-muted">
        {t("footerNote")}
      </p>
    </div>
  );
}
