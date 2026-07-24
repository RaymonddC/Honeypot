"use client";

/**
 * Add-transaction form (TAKEDOWN) — an analyst hand-enters a crypto transfer
 * (POST /api/casedata/crypto-transfers). It's merged into the Investigation
 * graph, so both endpoints become investigable. On success the parent re-traces
 * the destination wallet to show the new edge.
 */

import { useState } from "react";
import { useCases } from "@/components/cases/case-provider";
import { addCryptoTransfer } from "@/lib/casedata/api";

const CATEGORIES = ["unknown", "scam", "mule", "victim", "suspect", "exchange"];

export function AddTransaction({
  onAdded,
}: {
  onAdded: (toAddr: string) => void;
}) {
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
      setError(err instanceof Error ? err.message : "Failed to add transfer");
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="h-8 rounded-lg border border-white/10 bg-elevated px-3.5 text-xs font-semibold text-fg transition-colors hover:bg-white/[.07]"
      >
        + Add transaction
      </button>
    );
  }

  const field =
    "h-[34px] w-full rounded-lg border border-white/10 bg-card px-2.5 font-mono text-[12px] text-fg outline-none placeholder:text-muted focus:border-accent/40";

  return (
    <form
      onSubmit={submit}
      className="w-full rounded-card border border-line bg-card p-3.5"
    >
      <div className="mb-2.5 flex items-center justify-between">
        <span className="eyebrow">Add transaction → graph</span>
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            reset();
          }}
          className="text-[11px] text-muted hover:text-fg"
        >
          Cancel
        </button>
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-[10.5px] text-muted">From wallet</span>
          <input
            required
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            placeholder="T… source address"
            className={field}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[10.5px] text-muted">To wallet</span>
          <input
            required
            value={to}
            onChange={(e) => setTo(e.target.value)}
            placeholder="T… destination address"
            className={field}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[10.5px] text-muted">
            Amount (USDT)
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
          <span className="mb-1 block text-[10.5px] text-muted">
            Timestamp (optional)
          </span>
          <input
            type="datetime-local"
            value={ts}
            onChange={(e) => setTs(e.target.value)}
            className={field}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[10.5px] text-muted">Category</span>
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
        <p className="mt-2 text-[11px] text-risk-high">{error}</p>
      )}

      <div className="mt-3 flex justify-end">
        <button
          type="submit"
          disabled={busy}
          className="h-8 rounded-lg bg-accent px-4 text-xs font-semibold text-[#04140d] transition-colors hover:bg-accent-bright disabled:opacity-50"
        >
          {busy ? "Adding…" : "Add & trace"}
        </button>
      </div>
    </form>
  );
}
