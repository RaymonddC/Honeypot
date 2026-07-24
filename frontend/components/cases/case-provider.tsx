"use client";

/**
 * Active-case context — the spine of the case-centric flow. Holds the list of
 * cases and which one is "active"; the active case id is persisted to
 * localStorage and stamped as ``case_id`` on everything the analyst adds
 * (case-data, sessions). Loads lazily once a session exists.
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
import { useAuth } from "@/components/auth/auth-provider";
import {
  createCase as apiCreateCase,
  listCases as apiListCases,
  updateCase as apiUpdateCase,
  type Case,
  type CaseStage,
} from "@/lib/cases/api";

const ACTIVE_KEY = "ittu.activeCase";

interface CaseContextValue {
  cases: Case[];
  activeCase: Case | null;
  activeCaseId: string | null;
  loading: boolean;
  setActiveCase: (id: string | null) => void;
  createCase: (input: { title: string; crime_type?: string }) => Promise<Case>;
  advanceStage: (id: string, stage: CaseStage) => Promise<void>;
  refresh: () => Promise<void>;
}

const CaseContext = createContext<CaseContextValue | null>(null);

function readActive(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(ACTIVE_KEY);
  } catch {
    return null;
  }
}

export function CaseProvider({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const [cases, setCases] = useState<Case[]>([]);
  const [activeCaseId, setActiveId] = useState<string | null>(readActive());
  const [loading, setLoading] = useState(false);
  const bootedRef = useRef(false);

  const setActiveCase = useCallback((id: string | null) => {
    setActiveId(id);
    try {
      if (id) window.localStorage.setItem(ACTIVE_KEY, id);
      else window.localStorage.removeItem(ACTIVE_KEY);
    } catch {
      /* storage unavailable */
    }
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const list = await apiListCases();
      setCases(list);
      // Keep a sane active selection: honor stored id if still present,
      // else fall back to the newest case.
      setActiveId((cur) => {
        if (cur && list.some((c) => c.id === cur)) return cur;
        const next = list[0]?.id ?? null;
        try {
          if (next) window.localStorage.setItem(ACTIVE_KEY, next);
        } catch {
          /* ignore */
        }
        return next;
      });
    } catch {
      /* unauthenticated / backend down — leave list empty */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (status !== "authed" || bootedRef.current) return;
    bootedRef.current = true;
    void refresh();
  }, [status, refresh]);

  const createCase = useCallback(
    async (input: { title: string; crime_type?: string }) => {
      const created = await apiCreateCase(input);
      setCases((cur) => [created, ...cur]);
      setActiveCase(created.id);
      return created;
    },
    [setActiveCase],
  );

  const advanceStage = useCallback(async (id: string, stage: CaseStage) => {
    const updated = await apiUpdateCase(id, { stage });
    setCases((cur) => cur.map((c) => (c.id === id ? updated : c)));
  }, []);

  const activeCase = useMemo(
    () => cases.find((c) => c.id === activeCaseId) ?? null,
    [cases, activeCaseId],
  );

  const value = useMemo(
    () => ({
      cases,
      activeCase,
      activeCaseId,
      loading,
      setActiveCase,
      createCase,
      advanceStage,
      refresh,
    }),
    [cases, activeCase, activeCaseId, loading, setActiveCase, createCase, advanceStage, refresh],
  );

  return <CaseContext.Provider value={value}>{children}</CaseContext.Provider>;
}

export function useCases(): CaseContextValue {
  const ctx = useContext(CaseContext);
  if (!ctx) throw new Error("useCases must be used inside <CaseProvider>");
  return ctx;
}
