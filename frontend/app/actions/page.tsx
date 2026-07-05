"use client";

/**
 * Action Panel screen (UNCOVER) — one click turns a confirmed case into
 * legal action. Three generated-doc cards (freeze request PDF · goAML LTKM
 * draft · multi-agency alert) + a human-gated "Confirm & dispatch" control
 * with per-target POC "● mock" status and the SHA-256 evidence hash.
 * Consumes POST /api/actions/generate (+ /dispatch, GET /api/documents/{id})
 * and falls back to the local mock dataset when unreachable.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { AgencyAlertCard } from "@/components/actions/agency-alert-card";
import { DispatchBar } from "@/components/actions/dispatch-bar";
import { DocCard } from "@/components/actions/doc-card";
import { dispatchActions, generateActions } from "@/lib/actions/api";
import type { ActionBundle } from "@/lib/actions/types";

export default function ActionsPage() {
  const [bundle, setBundle] = useState<ActionBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [dispatching, setDispatching] = useState(false);
  const loadSeq = useRef(0);

  const generate = useCallback(async () => {
    const seq = ++loadSeq.current;
    setLoading(true);
    const result = await generateActions();
    if (seq !== loadSeq.current) return; // superseded
    setBundle(result);
    setLoading(false);
  }, []);

  useEffect(() => {
    void generate();
  }, [generate]);

  const dispatch = useCallback(async () => {
    if (!bundle || bundle.dispatched) return;
    setDispatching(true);
    const result = await dispatchActions(bundle);
    setBundle(result);
    setDispatching(false);
  }, [bundle]);

  return (
    <div className="mx-auto max-w-[1200px]">
      {/* ── header ─────────────────────────────────────────────────── */}
      <div className="mb-4 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Action Panel</h1>
          <p className="mt-1 text-xs text-muted">
            One click turns a confirmed case into legal action — every
            document hashed as evidence.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {bundle && (
            <span
              className={`rounded-md border px-2 py-0.5 font-mono text-[10.5px] font-semibold ${
                bundle.source === "api"
                  ? "border-accent/30 bg-accent/10 text-accent-bright"
                  : "border-risk-med/30 bg-risk-med/10 text-risk-med"
              }`}
              title={
                bundle.source === "api"
                  ? "Live backend API"
                  : "Backend unreachable — rendering local demo dataset"
              }
            >
              {bundle.source === "api" ? "● live api" : "● offline · mock"}
            </span>
          )}
          <button
            type="button"
            disabled={loading}
            onClick={() => void generate()}
            className="h-8 rounded-lg bg-accent px-3.5 text-xs font-semibold text-[#04140d] shadow-[0_0_16px_rgba(16,185,129,.28)] transition-colors hover:bg-accent-bright disabled:opacity-50"
          >
            {loading ? "Generating…" : "⎙ Generate all documents"}
          </button>
        </div>
      </div>

      {bundle && !loading ? (
        <>
          {/* ── provenance banner ──────────────────────────────────── */}
          <div className="mb-4 flex items-center gap-2.5 rounded-[9px] border border-accent/[.22] bg-accent/10 px-3.5 py-[9px] text-[11.5px] text-accent-bright">
            <span aria-hidden>◇</span>
            Generated from{" "}
            <span className="font-mono">{bundle.caseRef}</span> ·{" "}
            {bundle.summary} · reasoning attached to each artifact
          </div>

          {/* ── three doc cards ────────────────────────────────────── */}
          <div className="grid grid-cols-1 gap-3.5 md:grid-cols-3">
            {bundle.documents.map((doc) => (
              <DocCard key={doc.id} doc={doc} />
            ))}
            <AgencyAlertCard targets={bundle.targets} />
          </div>

          {/* ── human-gated dispatch ───────────────────────────────── */}
          <DispatchBar
            bundle={bundle}
            dispatching={dispatching}
            onDispatch={() => void dispatch()}
          />
        </>
      ) : (
        <div className="grid h-[420px] animate-pulse place-items-center rounded-card border border-line bg-card text-[11px] text-muted">
          Assembling freeze request · LTKM draft · multi-agency alert…
        </div>
      )}

      <div className="mt-5 border-t border-line pt-3.5 text-[10.5px] leading-relaxed text-muted">
        Every artifact is <b className="text-white/60">SHA-256 hashed</b> +
        timestamped into the case custody chain (UU ITE Pasal 5) and carries
        the Glass Box reasoning behind each risk flag. Generation is
        automatic; <b className="text-white/60">dispatch is human-gated</b> —
        POC mode routes to a mock sink, LIVE to goAML + IASC.
      </div>
    </div>
  );
}
