"use client";

/**
 * User Guide — an in-app orientation page: what ITTU is, the four-module
 * investigation flow, a screen-by-screen walkthrough, the POC↔LIVE data posture,
 * and the two engines analysts ask about most (honeypot scenarios + the wallet
 * risk model). Static content only — no API calls, no secrets. Matches the
 * ELSA card shell used across the app (see app/settings/page.tsx).
 */

import { useTranslations } from "next-intl";

type Module = {
  key: "infiltrate" | "trace" | "takedown" | "uncover";
  glyph: string;
  href: string;
};

const MODULES: Module[] = [
  { key: "infiltrate", glyph: "⬡", href: "/honeypot" },
  { key: "trace", glyph: "⇌", href: "/bridge" },
  { key: "takedown", glyph: "◉", href: "/investigation" },
  { key: "uncover", glyph: "⚑", href: "/actions" },
];

type Screen = {
  key: "caseFile" | "infiltrate" | "trace" | "takedown" | "uncover" | "commandCenter" | "controlPanel";
  glyph: string;
  href: string;
};

const SCREENS: Screen[] = [
  { key: "caseFile", glyph: "▤", href: "/case" },
  { key: "infiltrate", glyph: "⬡", href: "/honeypot" },
  { key: "trace", glyph: "⇌", href: "/bridge" },
  { key: "takedown", glyph: "◉", href: "/investigation" },
  { key: "uncover", glyph: "⚑", href: "/actions" },
  { key: "commandCenter", glyph: "▦", href: "/response" },
  { key: "controlPanel", glyph: "⚙", href: "/settings" },
];

const SCENARIOS = ["investmentScam", "judolDeposit", "cryptoPhishing"] as const;

/* ── Shared card shell (mirrors settings/page.tsx) ──────────────────────── */

function Card({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-3.5 rounded-card border border-line bg-card">
      <div className="border-b border-line px-3.5 py-3">
        <span className="eyebrow">{title}</span>
      </div>
      <div className="p-3.5">{children}</div>
    </div>
  );
}

function Glyph({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="flex h-7 w-7 flex-none items-center justify-center rounded-md bg-accent/10 text-sm text-accent-bright"
      aria-hidden
    >
      {children}
    </span>
  );
}

/* ── Page ───────────────────────────────────────────────────────────────── */

export default function GuidePage() {
  const t = useTranslations("guide.page");
  return (
    <div className="mx-auto max-w-[820px]">
      {/* header */}
      <div className="mb-4">
        <div className="eyebrow mb-1">{t("eyebrow")}</div>
        <h1 className="text-xl font-bold tracking-tight">
          {t("title")}
        </h1>
        <p className="mt-1 max-w-[62ch] text-xs leading-relaxed text-muted">
          {t("subtitle")}
        </p>
      </div>

      {/* the four modules */}
      <Card title={t("modulesCardTitle")}>
        <ul className="space-y-3">
          {MODULES.map((m) => (
            <li key={m.key} className="flex gap-3">
              <Glyph>{m.glyph}</Glyph>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[13px] font-semibold tracking-wide text-fg">
                    {t(`modules.${m.key}.name`)}
                  </span>
                  <a
                    href={m.href}
                    className="text-[11px] text-accent-bright hover:underline"
                  >
                    {t("open")}
                  </a>
                </div>
                <p className="mt-0.5 text-[12px] leading-relaxed text-muted">
                  {t(`modules.${m.key}.tagline`)}
                </p>
                <p className="mt-1 text-[11px] text-fg/70">
                  <span className="text-muted">{t("produces")}</span>{" "}
                  {t(`modules.${m.key}.produces`)}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </Card>

      {/* the flow */}
      <Card title={t("flowCardTitle")}>
        <div className="flex flex-wrap items-center gap-2 text-[12px]">
          {MODULES.map((m, i) => (
            <span key={m.key} className="flex items-center gap-2">
              <span className="rounded-md border border-line bg-elevated px-2.5 py-1 font-mono text-[11px] text-fg">
                {m.glyph} {t(`modules.${m.key}.name`)}
              </span>
              {i < MODULES.length - 1 && (
                <span className="text-muted" aria-hidden>
                  →
                </span>
              )}
            </span>
          ))}
        </div>
        <p className="mt-3 text-[12px] leading-relaxed text-muted">
          {t.rich("flowBody", {
            caseLink: (chunks) => (
              <a href="/case" className="text-accent-bright hover:underline">
                {chunks}
              </a>
            ),
            intake: (chunks) => <span className="text-fg/80">{chunks}</span>,
          })}
        </p>
      </Card>

      {/* screen walkthrough */}
      <Card title={t("screensCardTitle")}>
        <div className="space-y-2.5">
          {SCREENS.map((s) => (
            <div
              key={s.key}
              className="flex gap-3 rounded-lg border border-line bg-elevated px-3 py-2.5"
            >
              <Glyph>{s.glyph}</Glyph>
              <div className="min-w-0 flex-1">
                <a
                  href={s.href}
                  className="text-[13px] font-medium text-fg hover:text-accent-bright"
                >
                  {t(`screens.${s.key}.name`)}
                </a>
                <p className="mt-0.5 text-[11.5px] leading-snug text-muted">
                  <span className="text-fg/60">{t("seeLabel")}</span>{" "}
                  {t(`screens.${s.key}.see`)}
                </p>
                <p className="mt-0.5 text-[11.5px] leading-snug text-muted">
                  <span className="text-fg/60">{t("doLabel")}</span>{" "}
                  {t(`screens.${s.key}.doWhat`)}
                </p>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* POC vs LIVE */}
      <Card title={t("postureCardTitle")}>
        <p className="text-[12px] leading-relaxed text-muted">
          {t("postureIntro")}
        </p>
        <div className="mt-3 grid gap-2.5 sm:grid-cols-2">
          <div className="rounded-lg border border-risk-med/30 bg-risk-med/[.06] p-3">
            <span className="rounded-md border border-risk-med/40 bg-risk-med/10 px-2 py-0.5 font-mono text-[10px] font-bold tracking-widest text-risk-med">
              {t("postures.poc.badge")}
            </span>
            <p className="mt-2 text-[11.5px] leading-relaxed text-muted">
              {t.rich("postures.poc.body", {
                b: (chunks) => <span className="text-fg/80">{chunks}</span>,
              })}
            </p>
          </div>
          <div className="rounded-lg border border-accent/30 bg-accent/[.06] p-3">
            <span className="rounded-md border border-accent/40 bg-accent/10 px-2 py-0.5 font-mono text-[10px] font-bold tracking-widest text-accent-bright">
              {t("postures.live.badge")}
            </span>
            <p className="mt-2 text-[11.5px] leading-relaxed text-muted">
              {t("postures.live.body")}
            </p>
          </div>
        </div>
      </Card>

      {/* honeypot scenarios */}
      <Card title={t("scenariosCardTitle")}>
        <p className="mb-3 text-[12px] leading-relaxed text-muted">
          {t.rich("scenariosIntro", {
            honeypotLink: (chunks) => (
              <a href="/honeypot" className="text-accent-bright hover:underline">
                {chunks}
              </a>
            ),
          })}
        </p>
        <div className="space-y-2">
          {SCENARIOS.map((key) => (
            <div
              key={key}
              className="grid grid-cols-1 gap-1 rounded-lg border border-line bg-elevated px-3 py-2.5 sm:grid-cols-[9rem_1fr]"
            >
              <div className="text-[12.5px] font-medium text-fg">
                {t(`scenarios.${key}.name`)}
              </div>
              <div className="text-[11.5px] text-muted">
                <span className="font-mono text-fg/70">{t(`scenarios.${key}.persona`)}</span>
                <span className="mx-1.5 text-fg/30">·</span>
                {t("discloses", { discloses: t(`scenarios.${key}.discloses`) })}
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* risk model */}
      <Card title={t("riskModelCardTitle")}>
        <p className="text-[12px] leading-relaxed text-muted">
          {t.rich("riskModelBody", {
            b: (chunks) => <span className="text-fg/80">{chunks}</span>,
          })}
        </p>
        <p className="mt-2 text-[11.5px] text-muted">
          {t("riskModelApiNote")}{" "}
          <code className="rounded bg-elevated px-1.5 py-0.5 font-mono text-[11px] text-fg/80">
            GET /api/takedown/model-card
          </code>
          .
        </p>
      </Card>

      <p className="mb-2 mt-1 text-center text-[11px] text-muted">
        {t("footerTip")}
      </p>
    </div>
  );
}
