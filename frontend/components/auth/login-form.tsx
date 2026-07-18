"use client";

/**
 * Demo login card (POC): pick an agency + role → POST /api/auth/login →
 * JWT stored → redirect to /investigation. The Google button is the LIVE
 * path — visually present, disabled in POC (docs/Security-Evidence.md §1).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import Script from "next/script";
import { useAuth } from "./auth-provider";
import { AGENCIES, roleLabel } from "@/lib/auth/types";

// Minimal ambient shape for the Google Identity Services client (loaded at
// runtime from https://accounts.google.com/gsi/client). Only the two calls we use.
declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: {
            client_id: string;
            callback: (resp: { credential: string }) => void;
          }) => void;
          renderButton: (
            parent: HTMLElement,
            options: Record<string, unknown>,
          ) => void;
        };
      };
    };
  }
}

function GoogleMark() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden>
      <path
        fill="#4285F4"
        d="M23.5 12.27c0-.85-.08-1.66-.22-2.45H12v4.64h6.45a5.52 5.52 0 0 1-2.39 3.62v3h3.87c2.26-2.09 3.57-5.17 3.57-8.81z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.87-3c-1.07.72-2.44 1.14-4.06 1.14-3.12 0-5.77-2.11-6.71-4.95H1.29v3.1A11.99 11.99 0 0 0 12 24z"
      />
      <path
        fill="#FBBC05"
        d="M5.29 14.28a7.2 7.2 0 0 1 0-4.56v-3.1H1.29a12.02 12.02 0 0 0 0 10.76l4-3.1z"
      />
      <path
        fill="#EA4335"
        d="M12 4.77c1.76 0 3.34.61 4.59 1.8l3.43-3.43C17.94 1.19 15.23 0 12 0A11.99 11.99 0 0 0 1.29 6.62l4 3.1C6.23 6.88 8.88 4.77 12 4.77z"
      />
    </svg>
  );
}

export function LoginForm() {
  const { login, loginWithGoogle, loginOffline } = useAuth();
  const [agencyId, setAgencyId] = useState(AGENCIES[0].id);
  const [role, setRole] = useState(AGENCIES[0].roles[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [offlineOffer, setOfflineOffer] = useState(false);

  // Google Identity Services: the button is real only when a client ID is
  // configured for the browser (same value as the backend's ITTU_GOOGLE_CLIENT_ID).
  const googleClientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
  const googleBtnRef = useRef<HTMLDivElement>(null);
  const [gsiReady, setGsiReady] = useState(false);

  // Already loaded (remount / prior navigation) → skip waiting on the Script.
  useEffect(() => {
    if (window.google) setGsiReady(true);
  }, []);

  useEffect(() => {
    if (!googleClientId || !gsiReady || !googleBtnRef.current) return;
    const g = window.google;
    if (!g) return;
    g.accounts.id.initialize({
      client_id: googleClientId,
      callback: async (resp) => {
        setError(null);
        try {
          await loginWithGoogle(resp.credential);
        } catch (e) {
          setError(
            e instanceof Error && e.message
              ? `Google sign-in failed — ${e.message}`
              : "Google sign-in failed",
          );
        }
      },
    });
    googleBtnRef.current.innerHTML = ""; // avoid a stacked button on re-run
    g.accounts.id.renderButton(googleBtnRef.current, {
      theme: "filled_black",
      size: "large",
      text: "signin_with",
      width: 320,
    });
  }, [googleClientId, gsiReady, loginWithGoogle]);

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
          ? "Login failed — backend unreachable (is the API running on :8000?)"
          : `Login failed — ${e.message}`,
      );
      setOfflineOffer(unreachable);
      setBusy(false);
    }
  };

  return (
    <div className="w-full max-w-sm rounded-xl border border-line bg-card p-6">
      {/* Agency picker */}
      <fieldset>
        <legend className="eyebrow pb-2">Agency</legend>
        <div className="space-y-1" role="radiogroup" aria-label="Agency">
          {AGENCIES.map((a) => {
            const active = a.id === agencyId;
            return (
              <button
                key={a.id}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => pickAgency(a.id)}
                className={`flex w-full cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 text-left transition-colors ${
                  active
                    ? "border-accent/40 bg-accent/10"
                    : "border-line bg-elevated hover:border-white/10 hover:bg-white/[.04]"
                }`}
              >
                <span
                  className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md font-mono text-[11px] font-bold ${
                    active
                      ? "bg-accent/20 text-accent-bright"
                      : "bg-white/[.05] text-muted"
                  }`}
                  aria-hidden
                >
                  {a.mark}
                </span>
                <span className="min-w-0">
                  <span
                    className={`block truncate text-[13px] font-medium ${
                      active ? "text-fg" : "text-fg/80"
                    }`}
                  >
                    {a.name}
                  </span>
                  <span className="block truncate text-[11px] text-muted">
                    {a.sub}
                  </span>
                </span>
                <span
                  className={`ml-auto h-1.5 w-1.5 shrink-0 rounded-full ${
                    active ? "bg-accent" : "bg-transparent"
                  }`}
                  aria-hidden
                />
              </button>
            );
          })}
        </div>
      </fieldset>

      {/* Role picker */}
      <fieldset className="pt-4">
        <legend className="eyebrow pb-2">Role</legend>
        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Role">
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
                    : "border-line bg-elevated text-muted hover:border-white/10 hover:text-fg"
                }`}
              >
                {roleLabel(r)}
              </button>
            );
          })}
        </div>
      </fieldset>

      {error && (
        <p role="alert" className="pt-3 text-xs leading-relaxed text-risk-high">
          {error}
        </p>
      )}
      {offlineOffer && (
        <button
          type="button"
          onClick={() => loginOffline(agencyId, role)}
          className="mt-2 w-full cursor-pointer rounded-md border border-dashed border-line bg-elevated px-3 py-1.5 text-xs text-muted transition-colors hover:border-white/15 hover:text-fg"
        >
          Continue offline — demo session with mock data
        </button>
      )}

      {/* Enter */}
      <button
        type="button"
        onClick={submit}
        disabled={busy}
        className="mt-5 flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-[13px] font-semibold text-black transition-colors hover:bg-accent-bright disabled:cursor-default disabled:opacity-60"
      >
        {busy ? (
          <>
            <span
              className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-black/30 border-t-black"
              aria-hidden
            />
            Signing in…
          </>
        ) : (
          "Enter console"
        )}
      </button>
      <p className="pt-2 text-center text-[11px] text-muted">
        Demo sign-in · POC data mode · no credentials required
      </p>

      {/* Divider */}
      <div className="flex items-center gap-3 py-4" aria-hidden>
        <span className="h-px flex-1 bg-line" />
        <span className="text-[10px] uppercase tracking-widest text-muted">
          live
        </span>
        <span className="h-px flex-1 bg-line" />
      </div>

      {/* Google (LIVE path). Real GIS button when a client ID is configured;
          otherwise the disabled stub with a hint. */}
      {googleClientId ? (
        <>
          <Script
            src="https://accounts.google.com/gsi/client"
            strategy="afterInteractive"
            onLoad={() => setGsiReady(true)}
          />
          <div ref={googleBtnRef} className="flex min-h-[44px] justify-center" />
        </>
      ) : (
        <button
          type="button"
          disabled
          title="Set NEXT_PUBLIC_GOOGLE_CLIENT_ID to enable Google sign-in"
          className="flex w-full items-center justify-center gap-2.5 rounded-lg border border-line bg-elevated px-4 py-2.5 text-[13px] text-muted opacity-60"
        >
          <GoogleMark />
          Continue with Google
          <span className="rounded border border-line px-1 py-px font-mono text-[9px] tracking-widest">
            LIVE
          </span>
        </button>
      )}
    </div>
  );
}
