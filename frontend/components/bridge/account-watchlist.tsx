"use client";

/**
 * Bank-account watchlist (TRACE) — an analyst hand-enters bank accounts to
 * track (POST /api/casedata/bank-accounts). Each is listed here and flagged
 * "in flow" when its number appears among the accounts in the generated bridge
 * flow (GET /api/bridge/accounts).
 */

import { useCallback, useEffect, useState } from "react";
import { useCases } from "@/components/cases/case-provider";
import {
  addBankAccount,
  listWatchlistAccounts,
  type WatchlistedAccount,
} from "@/lib/casedata/api";

const CATEGORIES = ["unknown", "scam", "mule", "victim", "suspect", "exchange"];

export function AccountWatchlist() {
  const { activeCaseId } = useCases();
  const [items, setItems] = useState<WatchlistedAccount[]>([]);
  const [open, setOpen] = useState(false);
  const [bank, setBank] = useState("");
  const [number, setNumber] = useState("");
  const [holder, setHolder] = useState("");
  const [category, setCategory] = useState("mule");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setItems(await listWatchlistAccounts(activeCaseId));
    } catch {
      /* unauthenticated or backend down — leave list empty */
    }
  }, [activeCaseId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await addBankAccount({
        bank_name: bank.trim(),
        account_number: number.trim(),
        holder_name: holder.trim() || undefined,
        category,
        case_id: activeCaseId,
      });
      setBank("");
      setNumber("");
      setHolder("");
      setCategory("mule");
      setOpen(false);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add account");
    } finally {
      setBusy(false);
    }
  };

  const field =
    "h-[32px] w-full rounded-lg border border-white/10 bg-card px-2.5 font-mono text-[11.5px] text-fg outline-none placeholder:text-muted focus:border-accent/40";

  return (
    <div className="mt-3 rounded-card border border-line bg-card">
      <div className="flex items-center justify-between border-b border-line px-3.5 py-2.5">
        <span className="eyebrow">Tracked bank accounts</span>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="text-[11px] font-semibold text-accent-bright hover:underline"
        >
          {open ? "Cancel" : "+ Add"}
        </button>
      </div>

      {open && (
        <form onSubmit={submit} className="space-y-2 border-b border-line p-3">
          <input
            required
            value={bank}
            onChange={(e) => setBank(e.target.value)}
            placeholder="Bank (e.g. BCA)"
            className={field}
          />
          <input
            required
            value={number}
            onChange={(e) => setNumber(e.target.value)}
            placeholder="Account number"
            className={field}
          />
          <input
            value={holder}
            onChange={(e) => setHolder(e.target.value)}
            placeholder="Holder name (optional)"
            className={field}
          />
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
          {error && <p className="text-[11px] text-risk-high">{error}</p>}
          <button
            type="submit"
            disabled={busy}
            className="h-8 w-full rounded-lg bg-accent text-xs font-semibold text-[#04140d] transition-colors hover:bg-accent-bright disabled:opacity-50"
          >
            {busy ? "Adding…" : "Track account"}
          </button>
        </form>
      )}

      <div className="p-2">
        {items.length === 0 ? (
          <p className="px-1.5 py-2 text-[11px] text-muted">
            No tracked accounts yet.
          </p>
        ) : (
          <ul className="space-y-1">
            {items.map((a) => (
              <li
                key={a.id}
                className="flex items-center justify-between gap-2 rounded-lg bg-elevated px-2.5 py-1.5"
              >
                <div className="min-w-0">
                  <div className="truncate font-mono text-[11.5px] text-fg">
                    {a.bank_name} {a.account_number}
                  </div>
                  <div className="truncate text-[10.5px] text-muted">
                    {a.holder_name ? `a.n. ${a.holder_name} · ` : ""}
                    {a.category}
                  </div>
                </div>
                {a.seen_in_flow ? (
                  <span
                    className="flex-none rounded-md border border-risk-high/40 bg-risk-high/10 px-1.5 py-0.5 text-[9.5px] font-bold uppercase tracking-wide text-risk-high"
                    title="This account number appears in the current bridge flow"
                  >
                    in flow
                  </span>
                ) : (
                  <span className="flex-none rounded-md border border-line bg-card px-1.5 py-0.5 text-[9.5px] uppercase tracking-wide text-muted">
                    watch
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
