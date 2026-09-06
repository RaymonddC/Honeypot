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
import { useTranslations } from "next-intl";
import { useCases } from "@/components/cases/case-provider";
import { addBankAccount, addCryptoTransfer } from "@/lib/casedata/api";
import { GOLDEN, ONRAMP_CATEGORY } from "@/lib/demo/golden-thread";
import type { HpEntity } from "@/lib/honeypot/types";
import { entityIcon, formatConf } from "@/lib/honeypot/types";

function PromoteControl({
  e,
  onTraceWallet,
  alreadyTracked,
  onPromoted,
}: {
  e: HpEntity;
  onTraceWallet?: (addr: string) => void;
  /** This entity is already on the active case (from the case rollup). */
  alreadyTracked?: boolean;
  /** Something was attached to the case — ask the parent to reload its rollup. */
  onPromoted?: () => void;
}) {
  const t = useTranslations("honeypot.entityPanel");
  const { activeCaseId } = useCases();
  const [state, setState] = useState<"idle" | "busy" | "done" | "err">("idle");
  const full = e.rawValue ?? e.value;

  // Crypto wallet → trace it in Takedown (real on-chain trace; no fake edge).
  if (e.type === "crypto_wallet") {
    // Avoid deep-linking a truncated display value (mock/offline).
    if (full.includes("…")) return null;
    // In-case: attach the wallet to the case (as the fiat→crypto on-ramp edge,
    // so it threads on to Trace → Takedown → Uncover), then open Takedown on it.
    if (onTraceWallet)
      return (
        <button
          type="button"
          disabled={state === "busy"}
          onClick={async () => {
            setState("busy");
            try {
              if (activeCaseId)
                await addCryptoTransfer({
                  from_addr: GOLDEN.onrampSender,
                  to_addr: full,
                  value: GOLDEN.amountUsdt,
                  ts: new Date().toISOString(),
                  chain: "tron",
                  category: ONRAMP_CATEGORY,
                  case_id: activeCaseId,
                });
            } catch {
              // The wallet did NOT get attached, so Trace/Uncover downstream
              // won't see it. Say so and stay put rather than navigating to a
              // Takedown view that silently drops the case link.
              setState("err");
              return;
            }
            onTraceWallet(full);
          }}
          title={t("traceAttachTitle")}
          className="flex-none rounded-full border border-accent/40 bg-accent/10 px-1.5 py-0.5 text-[12px] font-semibold text-accent-bright transition-colors hover:bg-accent/20 disabled:opacity-40"
        >
          {state === "busy" ? "…" : state === "err" ? t("retry") : t("trace")}
        </button>
      );
    return (
      <Link
        href={`/investigation?address=${encodeURIComponent(full)}`}
        title={t("traceTitle")}
        className="flex-none rounded-full border border-accent/40 bg-accent/10 px-1.5 py-0.5 text-[12px] font-semibold text-accent-bright transition-colors hover:bg-accent/20"
      >
        {t("trace")}
      </Link>
    );
  }

  // Bank account → add to the active case (surfaces on BridgeWatch).
  if (e.type === "bank_account") {
    // Already on the case, either because this click just landed it there or
    // because a previous visit did. `alreadyTracked` comes from the case's own
    // rollup, so the state survives navigating away and back — without it the
    // control resets to "+ Case" and a second click files a duplicate account.
    if (state === "done" || alreadyTracked)
      return (
        <span className="flex-none text-[12px] font-semibold text-accent-bright" title={t("inCaseTitle")}>
          {t("inCase")}
        </span>
      );
    return (
      <button
        type="button"
        disabled={!activeCaseId || state === "busy"}
        onClick={async () => {
          setState("busy");
          try {
            await addBankAccount({
              bank_name: e.bankName || "unknown",
              account_number: full,
              category: "scam",
              case_id: activeCaseId,
            });
            // Golden-thread shortcut: promoting the known mule account also links
            // its collection wallet as the fiat→crypto on-ramp, so the whole
            // Trace → Takedown → Uncover chain lights up from this one click.
            if (activeCaseId && full === GOLDEN.bank.accountNumber)
              await addCryptoTransfer({
                from_addr: GOLDEN.onrampSender,
                to_addr: GOLDEN.wallet,
                value: GOLDEN.amountUsdt,
                ts: new Date().toISOString(),
                chain: "tron",
                category: ONRAMP_CATEGORY,
                case_id: activeCaseId,
              });
            setState("done");
            onPromoted?.();
          } catch {
            setState("err");
          }
        }}
        title={activeCaseId ? t("trackTitle") : t("openCaseTitle")}
        className="flex-none rounded-full border border-accent/40 bg-accent/10 px-1.5 py-0.5 text-[12px] font-semibold text-accent-bright transition-colors hover:bg-accent/20 disabled:opacity-40"
      >
        {state === "busy" ? "…" : state === "err" ? t("retry") : t("addCase")}
      </button>
    );
  }

  return null;
}

export function EntityPanel({
  entities,
  onTraceWallet,
  trackedAccounts,
  onPromoted,
}: {
  entities: HpEntity[];
  /** In-case: open the case's Takedown tab on a wallet (else it links out). */
  onTraceWallet?: (addr: string) => void;
  /** Account numbers already tracked on the active case — drives "in case". */
  trackedAccounts?: Set<string>;
  /** An entity was attached to the case — the parent should reload its rollup. */
  onPromoted?: () => void;
}) {
  const t = useTranslations("honeypot.entityPanel");
  return (
    <div className="mb-3.5 rounded-card border border-line bg-card">
      <div className="flex items-center justify-between border-b border-line px-3.5 py-3">
        <span className="eyebrow">{t("title")}</span>
        <span className="rounded-md border border-line bg-elevated px-2 py-0.5 text-[12px] text-muted">
          {t("validatedCount", { count: entities.length })}
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
              className="grid h-6 w-6 flex-none place-items-center rounded-md border border-line bg-elevated text-[12px]"
            >
              {entityIcon(e.type)}
            </div>
            <div className="min-w-0">
              <div className="truncate font-mono text-[12px] text-fg">
                {e.value}
              </div>
              <small className="block truncate text-[12px] text-muted">
                {e.subtitle}
              </small>
            </div>
            <div className="ml-auto flex flex-none items-center gap-2">
              {/* "conf" is a label, the score is the figure — only the figure
                  needs the mono face and tabular digits. */}
              <span className="text-[12px] text-muted" title={t("confidenceTitle")}>
                conf{" "}
                <b className="font-mono font-bold tnum text-accent-bright">
                  {formatConf(e.confidence)}
                </b>
              </span>
              <PromoteControl
                e={e}
                onTraceWallet={onTraceWallet}
                alreadyTracked={trackedAccounts?.has(e.rawValue ?? e.value)}
                onPromoted={onPromoted}
              />
            </div>
          </div>
        ))
      ) : (
        <div className="px-3.5 py-6 text-center text-[12px] text-muted">
          {t("empty")}
        </div>
      )}
    </div>
  );
}
