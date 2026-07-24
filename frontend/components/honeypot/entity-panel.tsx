"use client";

/**
 * Extracted-entities side panel — icon · monospace value · context · confidence.
 *
 * Each extracted bank account / wallet can be PROMOTED into the active case, so
 * a honeypot lead flows onward like any other input:
 *   · bank_account  → tracked account (shows on BridgeWatch)
 *   · crypto_wallet → traced in Takedown (Investigation graph)
 * That closes the loop: whatever the honeypot surfaces feeds the same pipeline
 * as a hand-entered account or transaction.
 */

import { useState } from "react";
import Link from "next/link";
import { useCases } from "@/components/cases/case-provider";
import { addBankAccount } from "@/lib/casedata/api";
import type { HpEntity } from "@/lib/honeypot/types";
import { entityIcon, formatConf } from "@/lib/honeypot/types";

function PromoteControl({
  e,
  onTraceWallet,
}: {
  e: HpEntity;
  onTraceWallet?: (addr: string) => void;
}) {
  const { activeCaseId } = useCases();
  const [state, setState] = useState<"idle" | "busy" | "done" | "err">("idle");
  const full = e.rawValue ?? e.value;

  // Crypto wallet → trace it in Takedown (real on-chain trace; no fake edge).
  if (e.type === "crypto_wallet") {
    // Avoid deep-linking a truncated display value (mock/offline).
    if (full.includes("…")) return null;
    // In-case: open the case's Takedown tab on this address; standalone: link out.
    if (onTraceWallet)
      return (
        <button
          type="button"
          onClick={() => onTraceWallet(full)}
          title="Trace this wallet in Takedown"
          className="flex-none rounded-md border border-accent/40 bg-accent/10 px-1.5 py-0.5 text-[9.5px] font-semibold text-accent-bright transition-colors hover:bg-accent/20"
        >
          Trace →
        </button>
      );
    return (
      <Link
        href={`/investigation?address=${encodeURIComponent(full)}`}
        title="Trace this wallet in Takedown"
        className="flex-none rounded-md border border-accent/40 bg-accent/10 px-1.5 py-0.5 text-[9.5px] font-semibold text-accent-bright transition-colors hover:bg-accent/20"
      >
        Trace →
      </Link>
    );
  }

  // Bank account → add to the active case (surfaces on BridgeWatch).
  if (e.type === "bank_account") {
    if (state === "done")
      return (
        <span className="flex-none text-[9.5px] font-semibold text-accent-bright" title="Added to case → BridgeWatch">
          ✓ in case
        </span>
      );
    return (
      <button
        type="button"
        disabled={!activeCaseId || state === "busy"}
        title={activeCaseId ? "Track on this case → BridgeWatch" : "Open a case to attach"}
        onClick={async () => {
          setState("busy");
          try {
            await addBankAccount({
              bank_name: e.bankName || "unknown",
              account_number: full,
              category: "scam",
              case_id: activeCaseId,
            });
            setState("done");
          } catch {
            setState("err");
          }
        }}
        className="flex-none rounded-md border border-accent/40 bg-accent/10 px-1.5 py-0.5 text-[9.5px] font-semibold text-accent-bright transition-colors hover:bg-accent/20 disabled:opacity-40"
      >
        {state === "busy" ? "…" : state === "err" ? "retry" : "+ Case"}
      </button>
    );
  }

  return null;
}

export function EntityPanel({
  entities,
  onTraceWallet,
}: {
  entities: HpEntity[];
  /** In-case: open the case's Takedown tab on a wallet (else it links out). */
  onTraceWallet?: (addr: string) => void;
}) {
  return (
    <div className="mb-3.5 rounded-card border border-line bg-card">
      <div className="flex items-center justify-between border-b border-line px-3.5 py-3">
        <span className="eyebrow">Extracted entities</span>
        <span className="rounded-md border border-line bg-elevated px-2 py-0.5 font-mono text-[10.5px] text-white/60">
          {entities.length} · validated
        </span>
      </div>

      {entities.length ? (
        entities.map((e) => (
          <div
            key={e.id}
            className="flex items-center gap-2.5 border-b border-line px-3.5 py-[9px] last:border-b-0"
          >
            <div
              aria-label={e.type.replace(/_/g, " ")}
              role="img"
              className="grid h-6 w-6 flex-none place-items-center rounded-md border border-line bg-elevated text-[11px]"
            >
              {entityIcon(e.type)}
            </div>
            <div className="min-w-0">
              <div className="truncate font-mono text-[11px] text-fg">
                {e.value}
              </div>
              <small className="block truncate text-[10px] text-muted">
                {e.subtitle}
              </small>
            </div>
            <div className="ml-auto flex flex-none items-center gap-2">
              <span className="font-mono text-[10px] tnum text-muted">
                conf{" "}
                <b className="font-bold text-accent-bright">
                  {formatConf(e.confidence)}
                </b>
              </span>
              <PromoteControl e={e} onTraceWallet={onTraceWallet} />
            </div>
          </div>
        ))
      ) : (
        <div className="px-3.5 py-6 text-center text-[11px] text-muted">
          No validated entities yet — the agent is still baiting.
        </div>
      )}
    </div>
  );
}
