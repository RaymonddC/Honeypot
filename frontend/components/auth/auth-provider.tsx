"use client";

/**
 * Client auth context (P5). Owns the JWT lifecycle:
 *   • boot: read localStorage token → optimistic session from JWT claims →
 *     confirm/refresh via GET /api/auth/me (POC keeps working offline).
 *   • login(agency, role): POST /api/auth/login → store token → hydrate /me.
 *   • logout(): clear token → /login.
 *   • listens for the global 401 event fired by lib/http.ts apiFetch.
 * Also loads GET /api/config so the shell's MODE badge reflects the real
 * deployment mode instead of a hardcoded env value.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import {
  UNAUTHORIZED_EVENT,
  clearToken,
  getToken,
  setToken,
  tokenLooksValid,
  tokenPayload,
} from "@/lib/http";
import {
  demoLogin,
  fetchConfig,
  fetchMe,
  mintOfflineToken,
} from "@/lib/auth/api";
import type { AppConfig, AuthMe } from "@/lib/auth/types";
import { AGENCIES, roleLabel } from "@/lib/auth/types";

export type AuthStatus = "loading" | "authed" | "anon";

interface AuthContextValue {
  status: AuthStatus;
  me: AuthMe | null;
  /** null until /api/config resolves (or its env fallback kicks in). */
  config: AppConfig | null;
  /** true once /api/auth/me confirmed the session against the live backend. */
  liveVerified: boolean;
  login: (agencyId: string, role: string) => Promise<void>;
  /** Offline demo session — locally minted token, mock data everywhere. */
  loginOffline: (agencyId: string, role: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/** Fallback session derived from JWT claims when /me is unreachable (offline demo). */
function meFromClaims(jwt: string): AuthMe | null {
  const p = tokenPayload(jwt);
  if (!p) return null;
  const agencyId = String(p.agency_id ?? "unknown");
  const known = AGENCIES.find((a) => a.id === agencyId);
  const role = String(p.role ?? "analyst");
  return {
    user: {
      id: String(p.sub ?? "demo"),
      name: typeof p.name === "string" && p.name ? p.name : roleLabel(role),
      email: typeof p.email === "string" ? p.email : undefined,
    },
    agency: { id: agencyId, name: known?.name ?? agencyId },
    role,
  };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [me, setMe] = useState<AuthMe | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [liveVerified, setLiveVerified] = useState(false);
  const bootedRef = useRef(false);

  const logout = useCallback(() => {
    clearToken();
    setMe(null);
    setLiveVerified(false);
    setStatus("anon");
    router.replace("/login");
  }, [router]);

  /** Hydrate `me` from the backend; fall back to JWT claims offline. */
  const hydrateMe = useCallback(async (jwt: string) => {
    try {
      const fresh = await fetchMe();
      setMe(fresh);
      setLiveVerified(true);
    } catch (err) {
      // 401 is handled by the UNAUTHORIZED_EVENT listener → logout (token
      // already cleared by the time we get here — don't resurrect a session).
      // Anything else (backend down) keeps the claims-derived session so
      // the demo still renders offline with mock data.
      if (getToken() === jwt) {
        const claims = meFromClaims(jwt);
        if (claims) setMe((cur) => cur ?? claims);
      }
      void err;
    }
  }, []);

  /* Boot: token → session; config → MODE badge. */
  useEffect(() => {
    if (bootedRef.current) return;
    bootedRef.current = true;

    fetchConfig().then(setConfig);

    const jwt = getToken();
    if (!tokenLooksValid(jwt)) {
      if (jwt) clearToken(); // expired remnant
      setStatus("anon");
      return;
    }
    setMe(meFromClaims(jwt!));
    setStatus("authed");
    void hydrateMe(jwt!);
  }, [hydrateMe]);

  /* Global 401 → session is dead, force re-login. */
  useEffect(() => {
    const onUnauthorized = () => logout();
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [logout]);

  const login = useCallback(
    async (agencyId: string, role: string) => {
      const { jwt, me: loginMe } = await demoLogin(agencyId, role);
      setToken(jwt);
      setMe(loginMe ?? meFromClaims(jwt));
      setStatus("authed");
      void hydrateMe(jwt);
      fetchConfig().then(setConfig);
      router.replace("/investigation");
    },
    [hydrateMe, router],
  );

  const loginOffline = useCallback(
    (agencyId: string, role: string) => {
      const jwt = mintOfflineToken(agencyId, role);
      setToken(jwt);
      setMe(meFromClaims(jwt));
      setLiveVerified(false);
      setStatus("authed");
      router.replace("/investigation");
    },
    [router],
  );

  const value = useMemo(
    () => ({ status, me, config, liveVerified, login, loginOffline, logout }),
    [status, me, config, liveVerified, login, loginOffline, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
