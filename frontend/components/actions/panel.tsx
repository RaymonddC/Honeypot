"use client";

/**
 * Action Panel screen (UNCOVER) — one click turns a confirmed case into
 * legal action. Three generated-doc cards (freeze request PDF · goAML LTKM
 * draft · multi-agency alert) + a human-gated "Confirm & dispatch" control
 * with per-target POC "● mock" status and the SHA-256 evidence hash.
 * Consumes POST /api/actions/generate (+ /dispatch, GET /api/documents/{id})
 * and falls back to the local mock dataset when unreachable.
 *
 * Rendered both as the standalone /actions page and embedded in the Case
 * File's Actions tab (pass ``embedded`` to drop the page chrome). Actions the
 * active case's tracked accounts + wallets either way.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { AgencyAlertCard } from "@/components/actions/agency-alert-card";
import { DispatchBar } from "@/components/actions/dispatch-bar";
import { DocCard } from "@/components/actions/doc-card";
import { useCases } from "@/components/cases/case-provider";
import { dispatchActions, generateActions } from "@/lib/actions/api";
import { fetchRollup } from "@/lib/cases/api";
import type { ActionBundle } from "@/lib/actions/types";

/** Assemble action entities from a case's tracked accounts + wallets. */
async function entitiesForCase(
  caseId: string,
): Promise<Array<Record<string, unknown>>> {
  try {
    const r = await fetchRollup(caseId);
    const banks = r.bank_accounts.map((b) => ({
      type: "bank_account",
      value: String(b.account_number),
      bank_name: b.bank_name ?? null,
      holder_name: b.holder_name ?? null,
    }));
    const seen = new Set<string>();
    const wallets: Array<Record<string, unknown>> = [];
    for (const t of r.crypto_transfers) {
      const addr = String(t.to_addr);
      if (seen.has(addr)) continue;
      seen.add(addr);
      wallets.push({ type: "crypto_wallet", value: addr, chain: String(t.chain ?? "tron") });
    }
    return [...wallets, ...banks];
  } catch {
    return [];
  }
}

// One bundle per (case · outputs · input-data version). Every POST
// /actions/generate creates a NEW bundle row on the case, so flipping tabs
// must reuse the last one — only "Generate" (force) or changed case data
// produces a fresh bundle. Module-level: survives tab switches (unmounts).
const bundleCache = new Map<string, ActionBundle>();

export function ActionsPanel({
  embedded = false,
  outputs,
  cacheSalt,
  onChanged,
}: {
  embedded?: boolean;
  /** Which documents to produce (e.g. ["freeze"] on the Freeze stage); omit = full set. */
  outputs?: string[];
  /** Changes when the case's input entities change → invalidates the cached bundle. */
  cacheSalt?: string;
  /**
   * Generating or dispatching wrote documents to the case. The embedding Case
   * File MUST reload its rollup on this: the stage checklist gates "Next" on
   * `documents > 0` and a dispatched document, and it reads those from the
   * rollup — not from this panel. Without it a successful dispatch leaves the
   * case insisting the freeze still hasn't been sent.
   */
  onChanged?: () => void;
}) {
  const t = useTranslations("actions.panel");
  const { activeCase } = useCases();
  // Stable key parts (array identity must not retrigger the effect).
  const outputsKey = outputs && outputs.length ? [...outputs].sort().join(",") : "all";
  const cacheKey = `${activeCase?.id ?? "demo"}|${outputsKey}|${cacheSalt ?? "-"}`;
  const freezeOnly = outputsKey === "freeze";

  const [bundle, setBundle] = useState<ActionBundle | null>(
    () => bundleCache.get(cacheKey) ?? null,
  );
  const [loading, setLoading] = useState(!bundleCache.has(cacheKey));
  const [dispatching, setDispatching] = useState(false);
  const loadSeq = useRef(0);

  // Held in a ref, deliberately: `generate` runs from an effect keyed on its own
  // identity, so taking `onChanged` as a dependency would make every parent
  // re-render (which a reload causes) re-run generation. The ref lets callers
  // pass a plain inline arrow without needing useCallback.
  const onChangedRef = useRef(onChanged);
  onChangedRef.current = onChanged;

  const generate = useCallback(
    async (force: boolean) => {
      const cached = bundleCache.get(cacheKey);
      if (!force && cached) {
        setBundle(cached);
        setLoading(false);
        return;
      }
      const seq = ++loadSeq.current;
      setLoading(true);
      // Action the ACTIVE case's own entities (falls back to the demo fixture
      // when there's no case or the case has no tracked data yet).
      const entities = activeCase ? await entitiesForCase(activeCase.id) : [];
      const result = await generateActions({
        caseId: activeCase?.id,
        crimeType: activeCase?.crime_type ?? undefined,
        outputs: outputsKey === "all" ? undefined : outputsKey.split(","),
        entities,
      });
      if (seq !== loadSeq.current) return; // superseded
      bundleCache.set(cacheKey, result);
      setBundle(result);
      setLoading(false);
      onChangedRef.current?.(); // documents now exist — refresh the case checklist
    },
    [activeCase, cacheKey, outputsKey],
  );

  useEffect(() => {
    void generate(false);
  }, [generate]);

  const dispatch = useCallback(async () => {
    if (!bundle || bundle.dispatched) return;
    setDispatching(true);
    const result = await dispatchActions(bundle);
    bundleCache.set(cacheKey, result);
    setBundle(result);
    setDispatching(false);
    // The freeze is now dispatched server-side. Tell the case, or its checklist
    // keeps reporting the dispatch step as outstanding and blocks "Next".
    onChangedRef.current?.();
  }, [bundle, cacheKey]);

  return (
    <div className={embedded ? "" : "mx-auto max-w-[1200px]"}>
      {/* ── header ─────────────────────────────────────────────────── */}
      <div
        className={`mb-5 flex flex-col items-start gap-3 sm:flex-row sm:items-start sm:gap-4 ${embedded ? "sm:justify-end" : "sm:justify-between"}`}
      >
        {!embedded && (
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{t("title")}</h1>
            <p className="mt-1.5 max-w-[62ch] text-[13px] leading-relaxed text-muted">{t("pageLead")}</p>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {/* data-source is plumbing — de-emphasized so the generated
              documents below keep the visual weight */}
          {bundle && (
            <span
              className={`rounded-md border px-1.5 py-0.5 text-[12px] ${
                bundle.source === "api"
                  ? "border-line bg-elevated text-muted"
                  : "border-risk-med/30 bg-risk-med/10 text-risk-med"
              }`}
              title={
                bundle.source === "api"
                  ? t("liveApiTitle")
                  : t("offlineMockTitle")
              }
            >
              {bundle.source === "api" ? t("liveApi") : t("offlineMock")}
            </span>
          )}
          <button
            type="button"
            disabled={loading}
            onClick={() => void generate(true)}
            title={t("regenerateTitle")}
            className="h-8 rounded-full bg-accent px-3.5 text-[12px] font-semibold text-[#090909] transition-colors hover:bg-accent-bright disabled:opacity-50"
          >
            {loading
              ? t("generating")
              : freezeOnly
                ? t("regenerateFreeze")
                : t("regenerateAll")}
          </button>
        </div>
      </div>

      {bundle && !loading ? (
        <>
          {/* ── provenance banner ──────────────────────────────────── */}
          <div className="mb-4 flex items-center gap-2.5 rounded-[10px] border border-[#262626] bg-[#141414] px-3.5 py-[9px] text-[12px] text-[#999]">
            {t("generatedFromPrefix")}{" "}
            <span >{bundle.caseRef}</span> ·{" "}
            {bundle.summary} · {t("reasoningAttached")}
          </div>

          {/* ── three doc cards ────────────────────────────────────── */}
          <div className="grid grid-cols-1 gap-3.5 md:grid-cols-3">
            {bundle.documents.map((doc) => (
              <DocCard
                key={doc.id}
                doc={doc}
                caseRef={bundle.caseRef}
                evidenceHash={bundle.evidenceHash}
                targets={bundle.targets}
              />
            ))}
            <AgencyAlertCard targets={bundle.targets} caseRef={bundle.caseRef} />
          </div>

          {/* ── human-gated dispatch ───────────────────────────────── */}
          <DispatchBar
            bundle={bundle}
            dispatching={dispatching}
            onDispatch={() => void dispatch()}
          />
        </>
      ) : (
        <div className="grid h-[420px] animate-pulse place-items-center rounded-card border border-line bg-card text-[12px] text-muted">
          {freezeOnly ? t("assemblingFreeze") : t("assemblingAll")}
        </div>
      )}

      {!embedded && (
        <div className="mt-5 border-t border-line pt-3.5 text-[12px] leading-relaxed text-muted">
          {t.rich("footerNote", {
            b: (chunks) => <b className="text-fg">{chunks}</b>,
          })}
        </div>
      )}
    </div>
  );
}
