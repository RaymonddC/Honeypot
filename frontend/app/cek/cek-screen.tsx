"use client";

/**
 * CekScam — the public check page (deck slide 05, Layer 1 · B2C).
 *
 * Written for Sari from slide 02: sells online, takes transfers from strangers,
 * and wants to know about an account BEFORE she ships. So the page is one input
 * and one answer — no login, no case, no investigator vocabulary, and it does
 * not sit inside the AppShell.
 *
 * The verdict wording is the load-bearing part. A tool like this is dangerous
 * if "we have no record" reads as "this is safe", because most scam accounts are
 * new and most checks will miss. The unknown state therefore says what it means
 * and still tells the user what to do.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Icon, type IconName } from "@/components/icon";
import { checkValue, detectKind, submitReport } from "@/lib/cekscam/api";
import { INDEX_SIZE } from "@/lib/cekscam/mock";
import type { CheckKind, CheckResult } from "@/lib/cekscam/types";
import { VERDICT_TONE } from "@/lib/cekscam/types";

const KIND_ICON: Record<CheckKind, IconName> = {
  bank_account: "bank",
  phone: "phone",
  ewallet: "bank",
  crypto_wallet: "wallet",
  url: "link",
  unknown: "entity",
};

const TONE_CLASS = {
  high: {
    ring: "border-risk-high/40 bg-risk-high/[.07]",
    text: "text-risk-high",
    dot: "bg-risk-high",
  },
  med: {
    ring: "border-risk-med/40 bg-risk-med/[.07]",
    text: "text-risk-med",
    dot: "bg-risk-med",
  },
  muted: {
    ring: "border-line bg-elevated",
    text: "text-fg",
    dot: "bg-muted",
  },
} as const;

/* ── Result ──────────────────────────────────────────────────────────────── */

function Verdict({ result }: { result: CheckResult }) {
  const t = useTranslations("cekscam");
  const tone = TONE_CLASS[VERDICT_TONE[result.verdict]];
  return (
    <div className={`rounded-card border p-4 sm:p-5 ${tone.ring}`}>
      <div className="flex flex-wrap items-start gap-x-4 gap-y-3">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <span className={`mt-0.5 flex-none ${tone.text}`}>
            <Icon
              name={
                result.verdict === "flagged"
                  ? "warning"
                  : result.verdict === "caution"
                    ? "freeze"
                    : "guide"
              }
              size={22}
            />
          </span>
          <div className="min-w-0">
            <div className={`text-[17px] font-semibold ${tone.text}`}>
              {t(`verdict.${result.verdict}.title`)}
            </div>
            <p className="mt-1 max-w-[52ch] text-[13px] leading-relaxed text-muted">
              {t(`verdict.${result.verdict}.body`)}
            </p>
          </div>
        </div>
        {result.confidence != null && (
          <div className="flex-none text-right">
            <div className={`text-[26px] font-bold leading-none tnum ${tone.text}`}>
              {Math.round(result.confidence * 100)}
              <span className="text-[13px] font-semibold"> %</span>
            </div>
            <div className="mt-1 text-[12px] uppercase tracking-wide text-muted">
              {t("confidenceLabel")}
            </div>
          </div>
        )}
      </div>

      {/* what was checked */}
      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-fg/10 pt-3.5 text-[12px]">
        <span className="flex items-center gap-1.5 rounded-md border border-line bg-card px-2 py-1 text-muted">
          <Icon name={KIND_ICON[result.kind]} size={12} />
          {t(`kind.${result.kind}`)}
        </span>
        <span className="break-all font-semibold text-fg">{result.value}</span>
        {result.label && <span className="text-muted">· {result.label}</span>}
      </div>

      {result.signals.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {result.signals.map((s) => (
            <li key={s.key} className="flex items-start gap-2 text-[12.5px] text-fg/85">
              <span className={`mt-[6px] h-1.5 w-1.5 flex-none rounded-full ${tone.dot}`} />
              {t(`signals.${s.key}`, s.values)}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 border-t border-fg/10 pt-3.5">
        <div className="eyebrow mb-1.5">{t("whatToDo")}</div>
        <p className="max-w-[62ch] text-[12.5px] leading-relaxed text-muted">
          {t(`verdict.${result.verdict}.advice`)}
        </p>
      </div>
    </div>
  );
}

/* ── Report form ─────────────────────────────────────────────────────────── */

function ReportForm({ prefill }: { prefill?: string }) {
  const t = useTranslations("cekscam");
  const [value, setValue] = useState(prefill ?? "");
  const [story, setStory] = useState("");
  const [amount, setAmount] = useState("");
  const [contact, setContact] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ ref: string; delivered: boolean } | null>(null);

  const field =
    "h-10 w-full rounded-[10px] border border-line bg-elevated px-3 text-[13px] text-fg outline-none placeholder:text-[#666] focus:border-accent-bright/60";

  if (done) {
    return (
      <div className="rounded-card border border-line bg-elevated p-4">
        <div className="flex items-center gap-2 text-[14px] font-semibold text-accent-bright">
          <Icon name="check" size={15} />
          {t("report.thanksTitle")}
        </div>
        <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
          {t("report.refLine", { ref: done.ref })}
        </p>
        {/* Never claim a delivery that did not happen. */}
        {!done.delivered && (
          <p className="mt-2 text-[12px] leading-relaxed text-risk-med">
            {t("report.notDelivered")}
          </p>
        )}
      </div>
    );
  }

  return (
    <form
      className="space-y-2.5"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!value.trim() || !story.trim()) return;
        setBusy(true);
        const r = await submitReport({
          kind: detectKind(value),
          value: value.trim(),
          story: story.trim(),
          amountIdr: amount.trim() ? Number(amount) : undefined,
          contact: contact.trim() || undefined,
        });
        setBusy(false);
        setDone(r);
      }}
    >
      <input
        required
        className={field}
        placeholder={t("report.valuePlaceholder")}
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
      <textarea
        required
        className={`${field} min-h-[88px] py-2.5 leading-relaxed`}
        placeholder={t("report.storyPlaceholder")}
        value={story}
        onChange={(e) => setStory(e.target.value)}
      />
      <div className="grid gap-2.5 sm:grid-cols-2">
        <input
          className={field}
          type="number"
          min="0"
          inputMode="numeric"
          placeholder={t("report.amountPlaceholder")}
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
        <input
          className={field}
          placeholder={t("report.contactPlaceholder")}
          value={contact}
          onChange={(e) => setContact(e.target.value)}
        />
      </div>
      <button
        type="submit"
        disabled={busy}
        className="h-10 w-full rounded-full bg-accent px-4 text-[13px] font-semibold text-on-accent transition-colors hover:bg-accent-bright disabled:opacity-60"
      >
        {busy ? t("report.sending") : t("report.submit")}
      </button>
      <p className="text-[12px] leading-relaxed text-muted">{t("report.privacy")}</p>
    </form>
  );
}

/* ── Page ────────────────────────────────────────────────────────────────── */

export function CekScreen() {
  const t = useTranslations("cekscam");
  const params = useSearchParams();
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<CheckResult | null>(null);
  const [busy, setBusy] = useState(false);

  const kind = query.trim() ? detectKind(query) : null;

  const check = useCallback(async (value: string) => {
    setBusy(true);
    setResult(await checkValue(value));
    setBusy(false);
  }, []);

  // A result is addressable: /cek?q=5271038462. Someone who finds a scam
  // account can send the answer to whoever needs it instead of describing it,
  // which is how a warning actually travels between people.
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current) return;
    const q = params.get("q");
    if (!q) return;
    seeded.current = true;
    setQuery(q);
    void check(q);
  }, [params, check]);

  const run = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    // Reflect it in the URL without a navigation, so back/forward and copy work.
    const url = `${window.location.pathname}?q=${encodeURIComponent(query.trim())}`;
    window.history.replaceState(null, "", url);
    await check(query);
  };

  return (
    <div className="min-h-screen bg-bg text-fg">
      {/* ── header ─────────────────────────────────────────────────────── */}
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-[860px] items-center gap-2.5 px-5 py-4">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/10 text-[13px] font-bold text-white">
            IT
          </span>
          <div className="min-w-0">
            <div className="text-[15px] font-semibold tracking-tight">{t("brand")}</div>
            <div className="text-[12px] text-muted">{t("brandSub")}</div>
          </div>
          <span className="ml-auto flex-none rounded-md border border-risk-med/30 bg-risk-med/10 px-2 py-1 text-[12px] text-risk-med">
            {t("demoBadge")}
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-[860px] px-5 pb-16 pt-8 sm:pt-12">
        {/* ── ask ──────────────────────────────────────────────────────── */}
        <h1 className="max-w-[18ch] text-[30px] font-semibold leading-[1.1] tracking-[-0.03em] sm:text-[38px]">
          {t("headline")}
        </h1>
        <p className="mt-3 max-w-[58ch] text-[14px] leading-relaxed text-muted">
          {t("subhead")}
        </p>

        <form onSubmit={run} className="mt-6">
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="flex h-12 flex-1 items-center gap-2.5 rounded-[12px] border border-line bg-card px-3.5 focus-within:border-accent-bright/60">
              <Icon name="search" size={17} className="flex-none text-muted" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                spellCheck={false}
                aria-label={t("inputLabel")}
                placeholder={t("inputPlaceholder")}
                className="min-w-0 flex-1 bg-transparent text-[14px] text-fg outline-none placeholder:text-[#666]"
              />
              {kind && kind !== "unknown" && (
                <span className="hidden flex-none items-center gap-1.5 rounded-md border border-line bg-elevated px-2 py-1 text-[12px] text-muted sm:flex">
                  <Icon name={KIND_ICON[kind]} size={12} />
                  {t(`kind.${kind}`)}
                </span>
              )}
            </div>
            <button
              type="submit"
              disabled={busy || !query.trim()}
              className="h-12 flex-none rounded-full bg-accent px-6 text-[14px] font-semibold text-on-accent transition-colors hover:bg-accent-bright disabled:opacity-50"
            >
              {busy ? t("checking") : t("check")}
            </button>
          </div>
          <p className="mt-2 text-[12px] text-muted">{t("inputHint")}</p>
        </form>

        {result && (
          <div className="mt-6">
            <Verdict result={result} />
          </div>
        )}

        {/* ── report ───────────────────────────────────────────────────── */}
        <section className="mt-10 rounded-card border border-line bg-card p-4 sm:p-5">
          <div className="eyebrow mb-1">{t("report.eyebrow")}</div>
          <h2 className="text-[17px] font-semibold tracking-tight">{t("report.title")}</h2>
          <p className="mb-4 mt-1 max-w-[62ch] text-[12.5px] leading-relaxed text-muted">
            {t("report.lead")}
          </p>
          <ReportForm prefill={result?.verdict === "unknown" ? result.value : undefined} />
        </section>

        {/* ── what this is and is not ──────────────────────────────────── */}
        <section className="mt-8 border-t border-line pt-5">
          <div className="eyebrow mb-2">{t("limits.eyebrow")}</div>
          <ul className="space-y-1.5 text-[12.5px] leading-relaxed text-muted">
            <li>{t("limits.demo", { count: INDEX_SIZE })}</li>
            <li>{t("limits.notSafe")}</li>
            <li>{t("limits.notOfficial")}</li>
          </ul>
        </section>
      </main>
    </div>
  );
}
