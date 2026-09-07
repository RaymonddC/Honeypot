"use client";

/**
 * Laporkan penipu — the public report (deck slide 05, Layer 1 · B2C).
 *
 * The other half of Layer 1, and its own page rather than a section under the
 * check: someone who has just been scammed arrives here directly, and a form
 * sitting below a search box reads as optional.
 *
 * Two taxonomies carry the weight. Slide 05 says every report "enters
 * INFILTRATE as honeypot training input and syndicate data" — prose can be
 * neither. `scamType` is what lets the agent pick a persona matched to the
 * method (slide 04); `channel` is what makes "channels used" clusterable.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Icon } from "@/components/icon";
import { detectKind, submitReport } from "@/lib/cekscam/api";
import type { ContactChannel, ScamType } from "@/lib/cekscam/types";
import { CONTACT_CHANNELS, SCAM_TYPES } from "@/lib/cekscam/types";

/** Compact chip row — a public form loses people fast, so the taxonomy is one
 *  tap rather than a dropdown and every field has a sensible default. */
function Chips<T extends string>({
  options,
  value,
  onChange,
  label,
  labelFor,
}: {
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
  label: string;
  /** Resolver rather than a key prefix: next-intl types t() against the message
   *  tree, and a key built from two dynamic halves cannot be narrowed. */
  labelFor: (option: T) => string;
}) {
  return (
    <fieldset>
      <legend className="mb-1.5 text-[12px] font-medium text-muted">{label}</legend>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => {
          const on = o === value;
          return (
            <button
              key={o}
              type="button"
              aria-pressed={on}
              onClick={() => onChange(o)}
              className={`rounded-full border px-3 py-1.5 text-[12px] transition-colors ${
                on
                  ? "border-white/25 bg-elevated font-semibold text-fg"
                  : "border-line bg-card text-muted hover:text-fg"
              }`}
            >
              {labelFor(o)}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

export function LaporScreen() {
  const t = useTranslations("cekscam");
  const params = useSearchParams();

  const [value, setValue] = useState("");
  const [scamType, setScamType] = useState<ScamType>("investment_scam");
  const [channel, setChannel] = useState<ContactChannel>("whatsapp");
  const [moneyMoved, setMoneyMoved] = useState(false);
  const [story, setStory] = useState("");
  const [amount, setAmount] = useState("");
  const [contact, setContact] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ ref: string; delivered: boolean } | null>(null);

  // Arriving from a check that came back unknown: carry the value across so it
  // does not have to be typed twice.
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current) return;
    const v = params.get("v");
    if (!v) return;
    seeded.current = true;
    setValue(v);
  }, [params]);

  const field =
    "h-10 w-full rounded-[10px] border border-line bg-elevated px-3 text-[13px] text-fg outline-none placeholder:text-[#666] focus:border-accent-bright/60";

  const submit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!value.trim() || !story.trim()) return;
      setBusy(true);
      const r = await submitReport({
        kind: detectKind(value),
        value: value.trim(),
        scamType,
        channel,
        moneyMoved,
        story: story.trim(),
        amountIdr: moneyMoved && amount.trim() ? Number(amount) : undefined,
        contact: contact.trim() || undefined,
      });
      setBusy(false);
      setDone(r);
    },
    [value, story, scamType, channel, moneyMoved, amount, contact],
  );

  if (done) {
    return (
      <>
        <h1 className="text-[30px] font-semibold leading-[1.1] tracking-[-0.03em] sm:text-[34px]">
          {t("report.thanksTitle")}
        </h1>
        <div className="mt-5 rounded-card border border-line bg-card p-4 sm:p-5">
          <div className="flex items-center gap-2 text-[14px] font-semibold text-accent-bright">
            <Icon name="check" size={15} />
            {t("report.refLine", { ref: done.ref })}
          </div>
          {/* Never claim a delivery that did not happen. */}
          {!done.delivered && (
            <p className="mt-3 max-w-[70ch] text-[12.5px] leading-relaxed text-risk-med">
              {t("report.notDelivered")}
            </p>
          )}
          <div className="mt-4 flex flex-wrap gap-2 border-t border-line pt-4">
            <button
              type="button"
              onClick={() => {
                setDone(null);
                setValue("");
                setStory("");
                setAmount("");
                setMoneyMoved(false);
              }}
              className="rounded-full border border-line bg-card px-3.5 py-2 text-[12.5px] font-semibold text-fg transition-colors hover:border-fg/25"
            >
              {t("report.another")}
            </button>
            <Link
              href="/cek"
              className="flex items-center gap-1.5 rounded-full border border-line bg-card px-3.5 py-2 text-[12.5px] font-semibold text-fg transition-colors hover:border-fg/25"
            >
              <Icon name="search" size={12} />
              {t("nav.check")}
            </Link>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <h1 className="max-w-[20ch] text-[30px] font-semibold leading-[1.1] tracking-[-0.03em] sm:text-[38px]">
        {t("report.title")}
      </h1>
      <p className="mt-3 max-w-[60ch] text-[14px] leading-relaxed text-muted">
        {t("report.lead")}
      </p>

      <form className="mt-6 space-y-3" onSubmit={submit}>
        <input
          required
          className={field}
          placeholder={t("report.valuePlaceholder")}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />

        <div className="grid gap-3 sm:grid-cols-2">
          <Chips
            options={SCAM_TYPES}
            value={scamType}
            onChange={setScamType}
            label={t("report.scamTypeLabel")}
            labelFor={(o) => t(`scamTypes.${o}`)}
          />
          <Chips
            options={CONTACT_CHANNELS}
            value={channel}
            onChange={setChannel}
            label={t("report.channelLabel")}
            labelFor={(o) => t(`channels.${o}`)}
          />
        </div>

        <textarea
          required
          className={`${field} min-h-[110px] py-2.5 leading-relaxed`}
          placeholder={t("report.storyPlaceholder")}
          value={story}
          onChange={(e) => setStory(e.target.value)}
        />

        {/* An attempt and a loss are different intelligence — asked, not
            inferred from whether an amount happens to be filled in. The page
            invites reports with no loss, so inferring would have discarded
            exactly those. */}
        <label className="flex cursor-pointer items-center gap-2.5 rounded-[10px] border border-line bg-elevated px-3 py-2.5">
          <input
            type="checkbox"
            checked={moneyMoved}
            onChange={(e) => setMoneyMoved(e.target.checked)}
            className="h-4 w-4 accent-[#0099ff]"
          />
          <span className="text-[12.5px] text-fg">{t("report.moneyMoved")}</span>
        </label>

        <div className="grid gap-3 sm:grid-cols-2">
          {moneyMoved && (
            <input
              className={field}
              type="number"
              min="0"
              inputMode="numeric"
              placeholder={t("report.amountPlaceholder")}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          )}
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
          className="h-11 w-full rounded-full bg-accent px-4 text-[13.5px] font-semibold text-on-accent transition-colors hover:bg-accent-bright disabled:opacity-60"
        >
          {busy ? t("report.sending") : t("report.submit")}
        </button>
        <p className="max-w-[70ch] text-[12px] leading-relaxed text-muted">
          {t("report.privacy")}
        </p>
      </form>
    </>
  );
}
