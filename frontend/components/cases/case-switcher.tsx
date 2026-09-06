"use client";

/**
 * Topbar case switcher — the active-case selector that anchors the whole flow.
 * Lists the agency's cases, lets you pick the active one (persisted), advance
 * its stage inline, and open a new case. Replaces the old static case chip.
 */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCases } from "@/components/cases/case-provider";
import { CASE_STAGES } from "@/lib/cases/api";

function stageColor(stage: string): string {
  if (stage === "closed") return "text-muted";
  if (stage === "freeze") return "text-risk-high";
  if (stage === "report" || stage === "recovery") return "text-accent-bright";
  return "text-risk-med";
}

export function CaseSwitcher() {
  const t = useTranslations("cases.switcher");
  const { cases, activeCase, setActiveCase, createCase, advanceStage } = useCases();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const submitNew = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    try {
      await createCase({ title: title.trim() });
      setTitle("");
      setCreating(false);
      setOpen(false);
      router.push("/case");
    } finally {
      setBusy(false);
    }
  };

  const label = activeCase ? activeCase.title : t("noCaseSelected");

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        title={activeCase ? t("activeCaseTitle", { stage: activeCase.stage }) : t("pickOrOpenCase")}
        className="flex min-w-0 max-w-[10rem] cursor-pointer items-center gap-2 rounded-md border border-line bg-elevated px-2.5 py-1 font-mono text-xs text-fg hover:border-fg/10 sm:max-w-[18rem]"
      >
        <span
          className={`h-1.5 w-1.5 rounded-full ${activeCase ? "bg-accent" : "bg-muted"}`}
          aria-hidden
        />
        <span className="truncate">{label}</span>
        {activeCase && (
          <span className={`text-[10px] uppercase ${stageColor(activeCase.stage)}`}>
            {activeCase.stage}
          </span>
        )}
        <span className="text-muted" aria-hidden>
          ▾
        </span>
      </button>

      {open && (
        <div
          role="menu"
          className="absolute left-0 top-9 z-50 w-72 rounded-lg border border-line bg-card p-1 shadow-xl shadow-black/50"
        >
          <div className="eyebrow px-3 pb-1 pt-2">{t("cases")}</div>
          <ul className="max-h-64 overflow-y-auto">
            {cases.length === 0 && (
              <li className="px-3 py-2 text-[11px] text-muted">{t("noCasesYet")}</li>
            )}
            {cases.map((c) => {
              const active = c.id === activeCase?.id;
              return (
                <li key={c.id}>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setActiveCase(c.id);
                      setOpen(false);
                    }}
                    className={`flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-[12.5px] transition-colors ${
                      active
                        ? "bg-accent/10 text-accent-bright"
                        : "text-muted hover:bg-fg/[.04] hover:text-fg"
                    }`}
                  >
                    <span className="min-w-0 truncate">{c.title}</span>
                    <span className={`flex-none text-[9.5px] uppercase ${stageColor(c.stage)}`}>
                      {c.stage}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>

          {/* advance-stage strip for the active case */}
          {activeCase && activeCase.stage !== "closed" && (
            <div className="mx-2 mt-1 border-t border-line pt-2">
              <div className="px-1 pb-1 text-[10px] text-muted">
                {t("advanceStage")}
              </div>
              <div className="flex flex-wrap gap-1 px-1 pb-1">
                {CASE_STAGES.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => void advanceStage(activeCase.id, s)}
                    className={`rounded px-1.5 py-0.5 text-[10px] transition-colors ${
                      s === activeCase.stage
                        ? "bg-accent/15 text-accent-bright"
                        : "bg-elevated text-muted hover:text-fg"
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="mx-2 my-1 h-px bg-line" aria-hidden />
          {creating ? (
            <form onSubmit={submitNew} className="p-2">
              <input
                autoFocus
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={t("newCaseTitlePlaceholder")}
                className="h-8 w-full rounded-md border border-line bg-elevated px-2.5 text-[12px] text-fg outline-none focus:border-accent/40"
              />
              <div className="mt-2 flex gap-2">
                <button
                  type="submit"
                  disabled={busy}
                  className="h-7 flex-1 rounded-full bg-accent text-[11px] font-semibold text-[#090909] hover:bg-accent-bright disabled:opacity-50"
                >
                  {busy ? t("opening") : t("openCase")}
                </button>
                <button
                  type="button"
                  onClick={() => setCreating(false)}
                  className="h-7 rounded-md border border-line px-2 text-[11px] text-muted hover:text-fg"
                >
                  {t("cancel")}
                </button>
              </div>
            </form>
          ) : (
            <button
              type="button"
              onClick={() => setCreating(true)}
              className="mb-1 flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-[12.5px] text-accent-bright transition-colors hover:bg-fg/[.04]"
            >
              <span aria-hidden>＋</span> {t("newCase")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
