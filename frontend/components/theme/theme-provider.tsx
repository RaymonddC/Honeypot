"use client";

/**
 * Client-side theme switcher — light / dark / system.
 *
 * Mirrors components/i18n/locale-provider.tsx: the choice lives in
 * localStorage (per-browser), read once on mount, changeable at runtime via
 * useTheme() below. "system" (the default) means no explicit .dark class —
 * app/globals.css's `@media (prefers-color-scheme: dark)` block then decides,
 * same as before this toggle existed. "light"/"dark" add or remove `.dark`
 * on <html>, which globals.css's `:root.dark` block treats as an override
 * that wins over the system preference in both directions.
 *
 * The flash-of-wrong-theme problem: this component can only apply the stored
 * choice AFTER React mounts, which is after the browser has already painted
 * once. See app/theme-init.ts + its inline <script> in app/layout.tsx for
 * the pre-hydration fix — that script runs before paint and does the same
 * localStorage read + class toggle synchronously, so this component's job at
 * mount is just to read the resulting DOM state back into React state (never
 * to *apply* the theme itself — it would be one frame too late).
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";

export type ThemeChoice = "light" | "dark" | "system";

const STORAGE_KEY = "ittu.theme";

type ThemeContextValue = {
  theme: ThemeChoice;
  setTheme: (next: ThemeChoice) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}

function isThemeChoice(value: string | null): value is ThemeChoice {
  return value === "light" || value === "dark" || value === "system";
}

function applyTheme(theme: ThemeChoice) {
  // Both classes are needed, not just .dark: globals.css's system-dark block
  // is scoped `:root:not(.light)` so an EXPLICIT light choice can override a
  // dark OS preference (the contract described there). Toggling only .dark
  // off for theme==="light" would leave that block still matching (no
  // .light present) and the page would stay dark despite the user's choice.
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.classList.toggle("light", theme === "light");
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // "system" on first render so server/client markup matches; the inline
  // pre-hydration script (app/layout.tsx) already painted the right class
  // by the time this runs, so this effect only needs to sync REACT's copy
  // of the choice from storage — the DOM is already correct.
  // Dark is the default ground (Framer near-black); the pre-paint init script
  // already added .dark for a first visit, so this just syncs React's copy.
  const [theme, setThemeState] = useState<ThemeChoice>("dark");

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      setThemeState(isThemeChoice(stored) ? stored : "dark");
    } catch {
      // localStorage unavailable — stay on the dark default.
    }
  }, []);

  // Keep in sync if the OS-level scheme changes while "system" is selected
  // (e.g. the OS flips to dark at sunset) — the .dark class is absent either
  // way under "system", but a listener isn't needed for correctness here;
  // this just exists so a live OS toggle doesn't require a reload. Cheap to
  // keep since it only re-runs the no-op class toggle when theme === "system".
  useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  const setTheme = useCallback((next: ThemeChoice) => {
    setThemeState(next);
    applyTheme(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // best-effort only — theme still applies for this session
    }
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}
