"use client";

/**
 * Client-side locale switcher — wraps next-intl's NextIntlClientProvider.
 * No [locale] route segment (see i18n/config.ts): the active locale lives in
 * localStorage (per-browser, like the Control Panel's voice settings), read
 * once on mount, and can be changed at runtime via `useLocale()` below.
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { NextIntlClientProvider } from "next-intl";
import { defaultLocale, isLocale, type Locale } from "@/i18n/config";
import idMessages from "@/messages/id.json";
import enMessages from "@/messages/en.json";

const STORAGE_KEY = "ittu.locale";

const MESSAGES: Record<Locale, typeof idMessages> = {
  id: idMessages,
  en: enMessages,
};

type LocaleContextValue = {
  locale: Locale;
  setLocale: (next: Locale) => void;
};

const LocaleContext = createContext<LocaleContextValue | null>(null);

export function useLocale(): LocaleContextValue {
  const ctx = useContext(LocaleContext);
  if (!ctx) throw new Error("useLocale must be used within LocaleProvider");
  return ctx;
}

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  // Start with the default on both server and first client render so
  // hydration matches; swap to the stored preference right after mount.
  const [locale, setLocaleState] = useState<Locale>(defaultLocale);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (isLocale(stored)) setLocaleState(stored);
    } catch {
      // localStorage unavailable (private mode, blocked) — stay on default.
    }
  }, []);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // best-effort only — locale still applies for this session
    }
  }, []);

  return (
    <LocaleContext.Provider value={{ locale, setLocale }}>
      {/* timeZone pinned explicitly — otherwise next-intl falls back to the
          environment's zone, which differs between the build machine (SSG)
          and the browser and throws IntlErrorCode.ENVIRONMENT_FALLBACK. This
          app is Indonesia-specific (WIB), so a fixed zone is also correct,
          not just quieter. */}
      <NextIntlClientProvider
        locale={locale}
        messages={MESSAGES[locale]}
        timeZone="Asia/Jakarta"
      >
        {children}
      </NextIntlClientProvider>
    </LocaleContext.Provider>
  );
}
