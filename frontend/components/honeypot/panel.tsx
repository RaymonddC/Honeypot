"use client";

/**
 * Honeypot console (INFILTRATE) — an AI persona baits the scammer and
 * silently extracts intel. Chat transcript with inline entity-extraction
 * badges → extracted-entities panel + chain-of-custody card → "Start voice
 * call" entry into the dedicated call view (/honeypot/call — P4b). Consumes
 * GET /sessions, /sessions/{id}/messages, /entities?session= and falls back
 * to the local mock transcript when the backend is unreachable.
 *
 * Rendered both as the standalone /honeypot page and embedded in the Case
 * File's Honeypot tab (pass ``embedded`` to drop the page chrome).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ChatTranscript } from "@/components/honeypot/chat-transcript";
import { CustodyCard } from "@/components/honeypot/custody-card";
import { EntityPanel } from "@/components/honeypot/entity-panel";
import { fetchHoneypotData } from "@/lib/honeypot/api";
import type { HoneypotData } from "@/lib/honeypot/types";

export function HoneypotPanel({
  embedded = false,
  onTraceWallet,
}: {
  embedded?: boolean;
  /** In-case: trace a surfaced wallet in the case's Takedown tab. */
  onTraceWallet?: (addr: string) => void;
}) {
  const t = useTranslations("honeypot.panel");
  const [data, setData] = useState<HoneypotData | null>(null);
  const [loading, setLoading] = useState(true);
  const loadSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++loadSeq.current;
    setLoading(true);
    const result = await fetchHoneypotData();
    if (seq !== loadSeq.current) return; // superseded
    setData(result);
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className={embedded ? "" : "mx-auto max-w-[1200px]"}>
      {/* ── header ─────────────────────────────────────────────────── */}
      <div
        className={`mb-4 flex flex-col items-start gap-3 sm:flex-row sm:items-end sm:gap-4 ${embedded ? "sm:justify-end" : "sm:justify-between"}`}
      >
        {!embedded && (
          <div>
            <h1 className="text-xl font-bold tracking-tight">
              {t("title")} <span className="font-semibold text-muted">· {t("titleModule")}</span>
            </h1>
            <p className="mt-1 text-xs text-muted">{t("subtitle")}</p>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {data && (
            <span
              className={`rounded-md border px-2 py-0.5 font-mono text-[10.5px] font-semibold ${
                data.source === "api"
                  ? "border-accent/30 bg-accent/10 text-accent-bright"
                  : "border-risk-med/30 bg-risk-med/10 text-risk-med"
              }`}
              title={
                data.source === "api"
                  ? t("liveApiTitle")
                  : t("offlineMockTitle")
              }
            >
              {data.source === "api" ? t("liveApi") : t("offlineMock")}
            </span>
          )}
          <button
            type="button"
            disabled={loading}
            onClick={() => void load()}
            className="h-8 rounded-lg border border-line bg-elevated px-3.5 text-xs font-semibold text-fg transition-colors hover:bg-fg/[.07] disabled:opacity-50"
          >
            {loading ? t("refreshing") : t("refreshSession")}
          </button>
          {/* P4b — dedicated voice-call view (repurposes the old indicator slot) */}
          <Link
            href="/honeypot/call"
            className="inline-flex h-8 items-center gap-2 rounded-lg border border-accent/40 bg-accent/10 px-3.5 text-xs font-semibold text-accent-bright transition-colors hover:bg-accent/20"
          >
            <svg
              aria-hidden
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ width: 13, height: 13 }}
            >
              <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" />
            </svg>
            {t("startVoiceCall")}
          </Link>
        </div>
      </div>

      {data && !loading ? (
        <div className="grid grid-cols-1 items-start gap-3.5 lg:grid-cols-[1fr_300px]">
          <ChatTranscript
            session={data.session}
            messages={data.messages}
            composerNote={data.composerNote}
          />
          <div>
            <EntityPanel entities={data.entities} onTraceWallet={onTraceWallet} />
            <CustodyCard custody={data.custody} />
          </div>
        </div>
      ) : (
        <div className="grid h-[452px] animate-pulse place-items-center rounded-card border border-line bg-card text-[11px] text-muted">
          {t("loadingState")}
        </div>
      )}

      {!embedded && (
        <div className="mt-5 border-t border-line pt-3.5 text-[10.5px] leading-relaxed text-muted">
          {t.rich("footerNote", {
            b: (chunks) => <b className="text-fg">{chunks}</b>,
          })}
        </div>
      )}
    </div>
  );
}
