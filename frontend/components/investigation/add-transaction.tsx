"use client";

/**
 * Add-transaction form (TAKEDOWN) — an analyst hand-enters a crypto transfer
 * (POST /api/casedata/crypto-transfers). It's merged into the Investigation
 * graph, so both endpoints become investigable. On success the parent re-traces
 * the destination wallet to show the new edge.
 */

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useCases } from "@/components/cases/case-provider";
import { addCryptoTransfer } from "@/lib/casedata/api";

const CATEGORIES = ["unknown", "scam", "mule", "victim", "suspect", "exchange"];

export function AddTransaction({
  onAdded,
}: {
  onAdded: (toAddr: string) => void;
}) {
  const t = useTranslations("investigation.addTransaction");
  const { activeCaseId } = useCases();
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [value, setValue] = useState("");
  const [ts, setTs] = useState("");
  const [category, setCategory] = useState("scam");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setFrom("");
    setTo("");
    setValue("");
    setTs("");
    setCategory("scam");
    setError(null);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await addCryptoTransfer({
        from_addr: from.trim(),
        to_addr: to.trim(),
        value: Number(value),
        ts: ts ? new Date(ts).toISOString() : new Date().toISOString(),
        chain: "tron",
        category,
        case_id: activeCaseId,
      });
      setOpen(false);
      reset();
      onAdded(to.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : t("errorFallback"));
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="h-8 rounded-lg border border-line bg-elevated px-3.5 text-[12px] font-semibold text-fg transition-colors hover:bg-fg/[.07]"
      >
        {t("addTransaction")}
      </button>
    );
  }

  const field =
    "h-9 w-full rounded-[10px] border border-[#262626] bg-[#1c1c1c] px-3 text-[13px] text-fg outline-none placeholder:text-[#666] focus:border-[#0099ff]/60";

  return (
    <form
      onSubmit={submit}
      className="w-full rounded-card border border-line bg-card p-3.5"
    >
      <div className="mb-2.5 flex items-center justify-between">
        <span className="eyebrow">{t("formTitle")}</span>
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            reset();
          }}
          className="text-[12px] text-muted hover:text-fg"
        >
          {t("cancel")}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-[12px] text-muted">{t("fromWallet")}</span>
          <input
            required
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            placeholder={t("fromWalletPlaceholder")}
            className={field}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] text-muted">{t("toWallet")}</span>
          <input
            required
            value={to}
            onChange={(e) => setTo(e.target.value)}
            placeholder={t("toWalletPlaceholder")}
            className={field}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] text-muted">
            {t("amountUsdt")}
          </span>
          <input
            required
            type="number"
            min="0"
            step="any"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="25000"
            className={field}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] text-muted">
            {t("timestampOptional")}
          </span>
          <input
            type="datetime-local"
            value={ts}
            onChange={(e) => setTs(e.target.value)}
            className={field}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] text-muted">{t("category")}</span>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className={`${field} font-sans`}
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && (
        <p className="mt-2 text-[12px] text-risk-high">{error}</p>
      )}

      <div className="mt-3 flex justify-end">
        <button
          type="submit"
          disabled={busy}
          className="h-8 rounded-full bg-accent px-4 text-[12px] font-semibold text-[#090909] transition-colors hover:bg-accent-bright disabled:opacity-50"
        >
          {busy ? t("adding") : t("addAndTrace")}
        </button>
      </div>
    </form>
  );
}
