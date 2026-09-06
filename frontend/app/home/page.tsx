"use client";

/**
 * Home — the front door. Two clearly separated paths so an investigator always
 * knows what to do:
 *   1. THE CASE FLOW (guided) — start/continue a case that walks the real
 *      lifecycle (intake → freeze → trace → takedown → report → recovery).
 *   2. QUICK TOOLS (ad hoc) — standalone tasks you can run without a case
 *      (trace a wallet, run a honeypot, look at the bridge…).
 * Same ELSA theme (cards, eyebrows, emerald accent) as the rest of the app.
 */

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCases } from "@/components/cases/case-provider";

type Tool = {
  key: "honeypot" | "bridge" | "investigation" | "actions" | "response";
  glyph: string;
  href: string;
};

const TOOLS: Tool[] = [
  { key: "honeypot", glyph: "⬡", href: "/honeypot" },
  { key: "bridge", glyph: "⇌", href: "/bridge" },
  { key: "investigation", glyph: "◉", href: "/investigation" },
  { key: "actions", glyph: "⚑", href: "/actions" },
  { key: "response", glyph: "▦", href: "/response" },
];

function Glyph({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="flex h-8 w-8 flex-none items-center justify-center rounded-full bg-accent/10 text-base text-accent-bright"
      aria-hidden
    >
      {children}
    </span>
  );
}

export default function HomePage() {
  const t = useTranslations("home.page");
  const router = useRouter();
  const { cases, activeCase, setActiveCase, createCase } = useCases();
  const [wallet, setWallet] = useState("");
  const [creating, setCreating] = useState(false);

  const recent = cases.slice(0, 4);

  // New report = open a fresh case; the Case File opens straight on its Intake
  // stage (the single victim-report form now lives there).
  const startReport = async () => {
    setCreating(true);
    try {
      await createCase({ title: `Scam report — ${new Date().toISOString().slice(0, 10)}` });
      router.push("/case");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="mx-auto max-w-[980px]">
      <div className="mb-5">
        <div className="eyebrow mb-1">{t("eyebrow")}</div>
        <h1 className="text-2xl font-bold tracking-tight">{t("title")}</h1>
        <p className="mt-1 text-[12px] text-muted">
          {t("subtitle")}
        </p>
      </div>

      {/* ── 1. THE CASE FLOW (guided) ─────────────────────────────────── */}
      <section className="mb-6">
        <div className="eyebrow mb-2 flex items-center gap-2">
          <span className="text-accent-bright">{t("section1Label")}</span>
          <span className="normal-case text-muted/60">{t("section1Hint")}</span>
        </div>

        <div className="rounded-card border border-accent/25 bg-accent/[.05] p-4">
          {activeCase ? (
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="min-w-0">
                <div className="text-[12px] text-muted">{t("activeCase")}</div>
                <div className="flex items-center gap-2.5">
                  <span className="truncate text-lg font-semibold text-fg">
                    {activeCase.title}
                  </span>
                  <span className="rounded border border-accent/30 bg-accent/10 px-1.5 py-0.5 text-[12px] font-bold uppercase tracking-wide text-accent-bright">
                    {activeCase.stage}
                  </span>
                </div>
                <div className="mt-0.5 text-[12px] text-muted">
                  {t("next", { task: t(`stageTask.${activeCase.stage}`) })}
                </div>
              </div>
              <div className="flex gap-2">
                <Link
                  href="/case"
                  className="h-9 rounded-full bg-accent px-4 text-[12px] font-semibold leading-9 text-[#090909] transition-colors hover:bg-accent-bright"
                >
                  {t("continueCase")}
                </Link>
                <button
                  type="button"
                  onClick={startReport}
                  disabled={creating}
                  className="h-9 rounded-lg border border-line bg-elevated px-4 text-[12px] font-semibold text-fg transition-colors hover:bg-fg/[.07] disabled:opacity-60"
                >
                  {creating ? t("opening") : t("newReport")}
                </button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <div className="text-[14px] font-semibold text-fg">
                  {t("startNewInvestigation")}
                </div>
                <p className="mt-0.5 max-w-[52ch] text-[12px] text-muted">
                  {t("startNewInvestigationDesc")}
                </p>
              </div>
              <button
                type="button"
                onClick={startReport}
                disabled={creating}
                className="h-9 rounded-full bg-accent px-4 text-[12px] font-semibold text-[#090909] transition-colors hover:bg-accent-bright disabled:opacity-60"
              >
                {creating ? t("opening") : t("newReportCta")}
              </button>
            </div>
          )}

          {recent.length > 0 && (
            <div className="mt-3.5 border-t border-accent/15 pt-3">
              <div className="mb-1.5 text-[12px] uppercase tracking-wide text-muted">
                {t("recentCases")}
              </div>
              <div className="flex flex-wrap gap-2">
                {recent.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => {
                      setActiveCase(c.id);
                      router.push("/case");
                    }}
                    className="flex items-center gap-2 rounded-lg border border-line bg-card px-2.5 py-1.5 text-left text-[12px] transition-colors hover:border-fg/15"
                  >
                    <span className="max-w-[14rem] truncate text-fg">{c.title}</span>
                    <span className="text-[12px] uppercase text-muted">{c.stage}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>

      {/* ── 2. QUICK TOOLS (ad hoc) ───────────────────────────────────── */}
      <section>
        <div className="eyebrow mb-2 flex items-center gap-2">
          <span>{t("section2Label")}</span>
          <span className="normal-case text-muted/60">{t("section2Hint")}</span>
        </div>

        {/* immediate task: trace a wallet */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (wallet.trim())
              router.push(`/investigation?address=${encodeURIComponent(wallet.trim())}`);
          }}
          className="mb-3 flex gap-2"
        >
          <div className="flex h-[38px] flex-1 items-center gap-2 rounded-lg border border-line bg-card px-3">
            <span className="text-muted" aria-hidden>⌕</span>
            <input
              value={wallet}
              onChange={(e) => setWallet(e.target.value)}
              spellCheck={false}
              placeholder={t("walletPlaceholder")}
              className="min-w-0 flex-1 bg-transparent font-mono text-[12.5px] text-fg outline-none placeholder:text-muted"
            />
          </div>
          <button
            type="submit"
            className="h-[38px] rounded-full bg-accent px-4 text-[12px] font-semibold text-[#090909] transition-colors hover:bg-accent-bright"
          >
            {t("trace")}
          </button>
        </form>

        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
          {TOOLS.map((tool) => (
            <Link
              key={tool.href}
              href={tool.href}
              className="group flex gap-3 rounded-card border border-line bg-card p-3.5 transition-colors hover:border-fg/15"
            >
              <Glyph>{tool.glyph}</Glyph>
              <div className="min-w-0">
                <div className="text-[13px] font-semibold text-fg group-hover:text-accent-bright">
                  {t(`tools.${tool.key}.title`)}
                </div>
                <p className="mt-0.5 text-[12px] leading-snug text-muted">
                  {t(`tools.${tool.key}.desc`)}
                </p>
              </div>
            </Link>
          ))}
        </div>

        <p className="mt-4 max-w-[72ch] border-t border-line pt-3.5 text-[12px] leading-relaxed text-muted">
          {t.rich("footerNote", {
            caseLink: (chunks) => (
              <Link href="/case" className="text-accent-bright hover:underline">
                {chunks}
              </Link>
            ),
          })}
        </p>
      </section>
    </div>
  );
}
