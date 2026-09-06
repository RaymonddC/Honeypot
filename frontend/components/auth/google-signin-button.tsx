"use client";

/**
 * LIVE Google Sign-In, styled to match ELSA (dark, accent) — NOT the stock
 * Google button. We render our own visual button and overlay the REAL Google
 * Identity Services (GIS) button on top at ~0 opacity so it captures the click
 * (GIS requires its own button to start the credential flow); the returned
 * `id_token` is exchanged for our JWT via the auth provider's `loginWithGoogle`
 * (POST /api/auth/google — backend verifies audience + maps email→agency/role).
 *
 * Renders NOTHING when NEXT_PUBLIC_GOOGLE_CLIENT_ID is unset (demo-only deploys).
 */

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useAuth } from "./auth-provider";

const CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
const GSI_SRC = "https://accounts.google.com/gsi/client";
const BTN_WIDTH = 320; // GIS button width; the overlay + visual button match it

declare global {
  interface Window {
    google?: {
      accounts?: {
        id?: {
          initialize: (cfg: Record<string, unknown>) => void;
          renderButton: (el: HTMLElement, opts: Record<string, unknown>) => void;
        };
      };
    };
  }
}

function GoogleG({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 48 48" className={className} aria-hidden>
      <path fill="#4285F4" d="M45.12 24.5c0-1.56-.14-3.06-.4-4.5H24v8.51h11.84c-.51 2.75-2.06 5.08-4.39 6.64v5.52h7.11c4.16-3.83 6.56-9.47 6.56-16.17z" />
      <path fill="#34A853" d="M24 46c5.94 0 10.92-1.97 14.56-5.33l-7.11-5.52c-1.97 1.32-4.49 2.1-7.45 2.1-5.73 0-10.58-3.87-12.31-9.07H4.34v5.7A21.99 21.99 0 0 0 24 46z" />
      <path fill="#FBBC05" d="M11.69 28.18A13.2 13.2 0 0 1 11 24c0-1.45.25-2.86.69-4.18v-5.7H4.34A22 22 0 0 0 2 24c0 3.55.85 6.91 2.34 9.88l7.35-5.7z" />
      <path fill="#EA4335" d="M24 10.75c3.23 0 6.13 1.11 8.41 3.29l6.31-6.31C34.91 4.18 29.93 2 24 2 15.4 2 7.96 6.94 4.34 14.12l7.35 5.7C13.42 14.62 18.27 10.75 24 10.75z" />
    </svg>
  );
}

export function GoogleSignInButton() {
  const t = useTranslations("auth.googleSignInButton");
  const { loginWithGoogle } = useAuth();
  const overlayRef = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!CLIENT_ID) return;
    let cancelled = false;

    const render = () => {
      const gid = window.google?.accounts?.id;
      if (cancelled || !gid || !overlayRef.current) return;
      gid.initialize({
        client_id: CLIENT_ID,
        callback: async (resp: { credential?: string }) => {
          if (!resp.credential) {
            setError(t("cancelled"));
            return;
          }
          setBusy(true);
          setError(null);
          try {
            await loginWithGoogle(resp.credential);
          } catch (e) {
            setError(e instanceof Error ? e.message : t("signInFailed"));
            setBusy(false);
          }
        },
      });
      overlayRef.current.replaceChildren(); // avoid double render on hot-reload
      gid.renderButton(overlayRef.current, {
        type: "standard",
        theme: "filled_black",
        size: "large",
        text: "continue_with",
        shape: "pill",
        width: BTN_WIDTH,
      });
    };

    const existing = document.querySelector<HTMLScriptElement>(`script[src="${GSI_SRC}"]`);
    if (window.google?.accounts?.id) {
      render();
    } else if (existing) {
      existing.addEventListener("load", render);
    } else {
      const s = document.createElement("script");
      s.src = GSI_SRC;
      s.async = true;
      s.defer = true;
      s.onload = render;
      s.onerror = () => setError(t("loadFailed"));
      document.head.appendChild(s);
    }
    return () => {
      cancelled = true;
    };
  }, [loginWithGoogle]);

  if (!CLIENT_ID) return null;

  return (
    <div className="mb-3">
      <div
        className="relative mx-auto h-10"
        style={{ width: BTN_WIDTH, maxWidth: "100%" }}
      >
        {/* Our ELSA-styled button (visual only; the overlay handles the click) */}
        <div
          aria-hidden
          className={`flex h-10 w-full items-center justify-center gap-2.5 rounded-full border border-line bg-elevated text-[13px] font-semibold text-fg transition-colors ${
            busy ? "opacity-60" : "hover:border-fg/20 hover:bg-fg/[.05]"
          }`}
        >
          {busy ? (
            <>
              <span
                className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-fg/25 border-t-fg/80"
                aria-hidden
              />
              {t("signingYouIn")}
            </>
          ) : (
            <>
              <GoogleG className="h-4 w-4" />
              {t("continueWithGoogle")}
            </>
          )}
        </div>
        {/* Real GIS button on top, ~invisible, captures the click. Hidden while
            busy so the spinner state isn't clickable. */}
        {!busy && (
          <div
            ref={overlayRef}
            className="absolute inset-0 z-10 flex items-center justify-center opacity-[0.02] [&_iframe]:!h-10 [&_iframe]:!w-full"
          />
        )}
      </div>

      {error && (
        <p role="alert" className="pt-2 text-center text-[12px] leading-relaxed text-risk-high">
          {error}
        </p>
      )}

      {/* divider before the demo agency/role picker */}
      <div className="mt-3 flex items-center gap-2.5">
        <span className="h-px flex-1 bg-line" />
        <span className="text-[12px] uppercase tracking-wide text-muted">{t("orDemoSignIn")}</span>
        <span className="h-px flex-1 bg-line" />
      </div>
    </div>
  );
}
