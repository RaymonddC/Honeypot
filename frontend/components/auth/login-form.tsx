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
    <div className="w-full rounded-[20px] border border-[#262626] bg-[#141414] p-4">
      {expired && (
        <p
          role="status"
          className="mb-3 rounded-[10px] border border-[#262626] bg-[#1c1c1c] px-3 py-2 text-[12px] leading-relaxed text-white"
        >
          <span className="font-medium">{t("sessionExpiredTitle")}</span>{" "}
          {t("sessionExpiredBody")}
        </p>
      )}
      {/* LIVE Google sign-in (hidden if no client id) — real auth; the picker
          below is the demo path. */}
      <GoogleSignInButton />

      {/* Agency picker — compact 2-col tile grid (selection = surface lift) */}
      <fieldset>
        <legend className="mb-1.5 text-[12px] font-medium uppercase tracking-widest text-[#999]">
          {t("agencyLegend")}
        </legend>
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
                className={`flex cursor-pointer items-center gap-2 rounded-[10px] border px-2 py-1.5 text-left transition-colors ${
                  active
                    ? "border-white/20 bg-[#1c1c1c]"
                    : "border-[#262626] bg-[#141414] hover:border-white/10 hover:bg-white/[.03]"
                }`}
              >
                <span
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[12px] font-bold ${
                    active ? "bg-white/10 text-white" : "bg-white/[.05] text-[#999]"
                  }`}
                  aria-hidden
                >
                  {a.mark}
                </span>
                <span
                  className={`min-w-0 truncate text-[12px] font-medium ${
                    active ? "text-white" : "text-white/70"
                  }`}
                >
                  {a.name}
                </span>
              </button>
            );
          })}
        </div>
      </fieldset>

      {/* Role picker — pill toggles */}
      <fieldset className="pt-3">
        <legend className="mb-1.5 text-[12px] font-medium uppercase tracking-widest text-[#999]">
          {t("roleLegend")}
        </legend>
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
                className={`cursor-pointer rounded-full border px-3 py-1 text-[12px] transition-colors ${
                  active
                    ? "border-white/20 bg-[#1c1c1c] font-medium text-white"
                    : "border-[#262626] bg-[#141414] text-[#999] hover:border-white/10 hover:text-white"
                }`}
              >
                {roleLabel(r, tRoles)}
              </button>
            );
          })}
        </div>
      </fieldset>

      {/* Capability — fixed two lines, so switching role never resizes the form.
          Flat (divider, not a nested card) to keep the surface hierarchy clean. */}
      <div className="mt-3 border-t border-[#262626] pt-3 text-[12px] leading-snug">
        <div className="truncate text-[#999]">
          <b className="text-white/80">{agency.name}</b> · {t("ownData")}
        </div>
        <div className="mt-1 flex items-center gap-1.5 whitespace-nowrap">
          <span
            className="h-1.5 w-1.5 flex-none rounded-full"
            style={{ background: dispatch ? "#0099ff" : "#666" }}
            aria-hidden
          />
          <span style={dispatch ? { color: "#0099ff" } : undefined} className={dispatch ? "" : "text-[#999]"}>
            {dispatch ? t("canDispatch") : t("receiveOnly")}
          </span>
        </div>
      </div>

      {error && (
        <p role="alert" className="pt-2.5 text-[12px] leading-relaxed text-[#ff5577]">
          {error}
        </p>
      )}
      {offlineOffer && (
        <button
          type="button"
          onClick={() => loginOffline(agencyId, role)}
          className="mt-2 w-full cursor-pointer rounded-full border border-dashed border-[#333] bg-[#1c1c1c] px-3 py-1.5 text-[12px] text-[#999] transition-colors hover:border-white/15 hover:text-white"
        >
          {t("continueOffline")}
        </button>
      )}

      {/* Enter — the white pill CTA (Framer primary) */}
      <button
        type="button"
        onClick={submit}
        disabled={busy}
        className="mt-3.5 flex w-full cursor-pointer items-center justify-center gap-2 rounded-full bg-white px-4 py-2.5 text-[13px] font-medium text-[#090909] transition-transform hover:brightness-95 active:scale-[.99] disabled:cursor-default disabled:opacity-60"
        style={{ letterSpacing: "-0.14px" }}
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
      <p className="pt-2 text-center text-[12px] text-[#999]">
        {t("footer")}
      </p>
    </div>
  );
}
