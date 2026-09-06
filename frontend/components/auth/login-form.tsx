"use client";

/**
 * Demo login card (POC): pick an agency + role → POST /api/auth/login → JWT
 * stored → redirect into the console. On a backend-unreachable error, offers a
 * local offline demo session.
 */

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useAuth } from "./auth-provider";
import { takeLogoutReason } from "@/lib/http";
import { GoogleSignInButton } from "./google-signin-button";
import { AGENCIES, canDispatch, roleLabel } from "@/lib/auth/types";

export function LoginForm() {
  const t = useTranslations("login");
  const tRoles = useTranslations("roles");
  const { login, loginOffline } = useAuth();
  const [agencyId, setAgencyId] = useState(AGENCIES[0].id);
  const [role, setRole] = useState(AGENCIES[0].roles[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [offlineOffer, setOfflineOffer] = useState(false);
  const [expired, setExpired] = useState(false);

  // Read once on mount (and clear): explains an involuntary bounce back here.
  // Effect, not render — sessionStorage doesn't exist during SSR.
  useEffect(() => {
    if (takeLogoutReason() === "expired") setExpired(true);
  }, []);

  const agency = useMemo(
    () => AGENCIES.find((a) => a.id === agencyId) ?? AGENCIES[0],
    [agencyId],
  );

  const pickAgency = (id: string) => {
    setAgencyId(id);
    const next = AGENCIES.find((a) => a.id === id);
    if (next && !next.roles.includes(role)) setRole(next.roles[0]);
    setError(null);
  };

  const submit = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await login(agencyId, role);
    } catch (e) {
      const unreachable =
        !(e instanceof Error) ||
        !e.message ||
        e.message === "Failed to fetch" ||
        /abort|network|fetch/i.test(e.name + e.message);
      setError(
        unreachable
          ? t("errorUnreachable")
          : t("errorGeneric", { message: e.message }),
      );
      setOfflineOffer(unreachable);
      setBusy(false);
    }
  };

  const dispatch = canDispatch(role);

  return (
    <div className="w-full rounded-xl border border-line bg-card p-4">
      {expired && (
        <p
          role="status"
          className="mb-3 rounded-md border border-risk-med/30 bg-risk-med/10 px-3 py-2 text-xs leading-relaxed text-fg"
        >
          <span className="font-medium">{t("sessionExpiredTitle")}</span>{" "}
          {t("sessionExpiredBody")}
        </p>
      )}
      {/* LIVE Google sign-in (hidden if no client id) — real auth; the picker
          below is the demo path. */}
      <GoogleSignInButton />

      {/* Agency picker — compact 2-col tile grid */}
      <fieldset>
        <legend className="eyebrow pb-1.5">{t("agencyLegend")}</legend>
        <div className="grid grid-cols-2 gap-1.5" role="radiogroup" aria-label={t("agencyLegend")}>
          {AGENCIES.map((a) => {
            const active = a.id === agencyId;
            return (
              <button
                key={a.id}
                type="button"
                role="radio"
                aria-checked={active}
                title={a.sub}
                onClick={() => pickAgency(a.id)}
                className={`flex cursor-pointer items-center gap-2 rounded-lg border px-2 py-1.5 text-left transition-colors ${
                  active
                    ? "border-accent/40 bg-accent/10"
                    : "border-line bg-elevated hover:border-fg/10 hover:bg-fg/[.04]"
                }`}
              >
                <span
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md font-mono text-[10px] font-bold ${
                    active ? "bg-accent/20 text-accent-bright" : "bg-fg/[.05] text-muted"
                  }`}
                  aria-hidden
                >
                  {a.mark}
                </span>
                <span
                  className={`min-w-0 truncate text-[12px] font-medium ${
                    active ? "text-fg" : "text-fg/80"
                  }`}
                >
                  {a.name}
                </span>
              </button>
            );
          })}
        </div>
      </fieldset>

      {/* Role picker */}
      <fieldset className="pt-3">
        <legend className="eyebrow pb-1.5">{t("roleLegend")}</legend>
        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={t("roleLegend")}>
          {agency.roles.map((r) => {
            const active = r === role;
            return (
              <button
                key={r}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => setRole(r)}
                className={`cursor-pointer rounded-md border px-2.5 py-1 text-xs transition-colors ${
                  active
                    ? "border-accent/40 bg-accent/10 font-medium text-accent-bright"
                    : "border-line bg-elevated text-muted hover:border-fg/10 hover:text-fg"
                }`}
              >
                {roleLabel(r, tRoles)}
              </button>
            );
          })}
        </div>
      </fieldset>

      {/* Capability — fixed two lines, so switching role never resizes the form */}
      <div className="mt-3 rounded-lg border border-line bg-elevated px-2.5 py-2 text-[10.5px] leading-snug">
        <div className="truncate text-muted">
          <b className="text-fg/80">{agency.name}</b> · {t("ownData")}
        </div>
        <div className="mt-1 flex items-center gap-1.5 whitespace-nowrap">
          <span
            className={`h-1.5 w-1.5 flex-none rounded-full ${dispatch ? "bg-accent" : "bg-risk-med"}`}
            aria-hidden
          />
          <span className={dispatch ? "text-accent-bright" : "text-risk-med"}>
            {dispatch ? t("canDispatch") : t("receiveOnly")}
          </span>
        </div>
      </div>

      {error && (
        <p role="alert" className="pt-2.5 text-xs leading-relaxed text-risk-high">
          {error}
        </p>
      )}
      {offlineOffer && (
        <button
          type="button"
          onClick={() => loginOffline(agencyId, role)}
          className="mt-2 w-full cursor-pointer rounded-md border border-dashed border-line bg-elevated px-3 py-1.5 text-xs text-muted transition-colors hover:border-fg/15 hover:text-fg"
        >
          {t("continueOffline")}
        </button>
      )}

      {/* Enter */}
      <button
        type="button"
        onClick={submit}
        disabled={busy}
        className="mt-3.5 flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-[13px] font-semibold text-black transition-colors hover:bg-accent-bright disabled:cursor-default disabled:opacity-60"
      >
        {busy ? (
          <>
            <span
              className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-black/30 border-t-black"
              aria-hidden
            />
            {t("signingIn")}
          </>
        ) : (
          t("enterConsole")
        )}
      </button>
      <p className="pt-2 text-center text-[11px] text-muted">
        {t("footer")}
      </p>
    </div>
  );
}
