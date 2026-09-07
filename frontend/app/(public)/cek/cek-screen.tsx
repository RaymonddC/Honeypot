"use client";

/**
 * CekScam — check an account before you transfer (deck slide 05, Layer 1 · B2C).
 *
 * Written for Sari from slide 02: sells online, takes transfers from strangers,
 * wants to know about an account BEFORE she ships. So it is one input and one
 * answer, with no login and no investigator vocabulary.
 *
 * The verdict wording is the load-bearing part. A tool like this is dangerous
 * if "we have no record" reads as "this is safe", because most scam accounts
 * are new and most checks will miss. The unknown state says what it means and
 * still gives the reader something to act on.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Icon, type IconName } from "@/components/icon";
import { checkValue, detectKind } from "@/lib/cekscam/api";
import { SAMPLES } from "@/lib/cekscam/mock";
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
  high: { ring: "border-risk-high/40 bg-risk-high/[.07]", text: "text-risk-high", dot: "bg-risk-high" },
  med: { ring: "border-risk-med/40 bg-risk-med/[.07]", text: "text-risk-med", dot: "bg-risk-med" },
  muted: { ring: "border-line bg-elevated", text: "text-fg", dot: "bg-muted" },
} as const;

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

      {/* The hand-off to the other page. Strongest exactly where the database
          was no help: an unrecognised account is the one most worth adding. */}
      <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-fg/10 pt-3.5">
        <p className="min-w-0 flex-1 text-[12px] leading-relaxed text-muted">
          {t(`crossLink.${result.verdict}`)}
        </p>
        <Link
          href={`/lapor?v=${encodeURIComponent(result.value)}`}
          className="flex flex-none items-center gap-1.5 rounded-full border border-line bg-card px-3 py-1.5 text-[12px] font-semibold text-fg transition-colors hover:border-fg/25"
        >
          <Icon name="uncover" size={12} />
          {t("crossLink.cta")}
        </Link>
      </div>
    </div>
  );
}

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

  const submit = useCallback(
    async (value: string) => {
      // Reflect it in the URL without navigating, so a result can be sent to
      // whoever needs it instead of described, and back/forward still work.
      window.history.replaceState(
        null,
        "",
        `${window.location.pathname}?q=${encodeURIComponent(value)}`,
      );
      await check(value);
    },
    [check],
  );

  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current) return;
    const q = params.get("q");
    if (!q) return;
    seeded.current = true;
    setQuery(q);
    void check(q);
  }, [params, check]);

  return (
    <>
      <h1 className="max-w-[18ch] text-[30px] font-semibold leading-[1.1] tracking-[-0.03em] sm:text-[38px]">
        {t("headline")}
      </h1>
      <p className="mt-3 max-w-[58ch] text-[14px] leading-relaxed text-muted">{t("subhead")}</p>

      <form
        className="mt-6"
        onSubmit={(e) => {
          e.preventDefault();
          if (query.trim()) void submit(query.trim());
        }}
      >
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

      {/* One-tap examples. Without them you have to already know a scam account
          to see what this page does. */}
      <div className="mt-4 flex flex-wrap items-center gap-1.5">
        <span className="text-[12px] text-muted">{t("samples.label")}</span>
        {SAMPLES.map((s) => (
          <button
            key={s.value}
            type="button"
            onClick={() => {
              setQuery(s.value);
              void submit(s.value);
            }}
            className="rounded-full border border-line bg-card px-2.5 py-1 text-[12px] text-muted transition-colors hover:border-fg/25 hover:text-fg"
          >
            {t(`samples.${s.labelKey}`)}
          </button>
        ))}
      </div>

      {result && (
        <div className="mt-6">
          <Verdict result={result} />
        </div>
      )}
    </>
  );
}
