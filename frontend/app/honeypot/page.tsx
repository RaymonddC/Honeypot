"use client";

/**
 * Honeypot console (INFILTRATE) — an AI persona baits the scammer and
 * silently extracts intel. Chat transcript with inline entity-extraction
 * badges → extracted-entities panel + chain-of-custody card → voice-call
 * indicator (visual only — P4b). Consumes GET /sessions, /sessions/{id}/
 * messages, /entities?session= and falls back to the local mock transcript
 * when the backend is unreachable.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ChatTranscript } from "@/components/honeypot/chat-transcript";
import { CustodyCard } from "@/components/honeypot/custody-card";
import { EntityPanel } from "@/components/honeypot/entity-panel";
import { VoiceIndicator } from "@/components/honeypot/voice-indicator";
import { fetchHoneypotData } from "@/lib/honeypot/api";
import type { HoneypotData } from "@/lib/honeypot/types";

export default function HoneypotPage() {
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
    <div className="mx-auto max-w-[1200px]">
      {/* ── header ─────────────────────────────────────────────────── */}
      <div className="mb-4 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight">
            Honeypot <span className="font-semibold text-muted">· INFILTRATE</span>
          </h1>
          <p className="mt-1 text-xs text-muted">
            An AI persona baits the scammer and silently extracts intel —
            strictly reactive, chain-of-custody logged.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {data && (
            <span
              className={`rounded-md border px-2 py-0.5 font-mono text-[10.5px] font-semibold ${
                data.source === "api"
                  ? "border-accent/30 bg-accent/10 text-accent-bright"
                  : "border-risk-med/30 bg-risk-med/10 text-risk-med"
              }`}
              title={
                data.source === "api"
                  ? "Live backend API"
                  : "Backend unreachable — rendering local demo dataset"
              }
            >
              {data.source === "api" ? "● live api" : "● offline · mock"}
            </span>
          )}
          <button
            type="button"
            disabled={loading}
            onClick={() => void load()}
            className="h-8 rounded-lg border border-white/10 bg-elevated px-3.5 text-xs font-semibold text-fg transition-colors hover:bg-white/[.07] disabled:opacity-50"
          >
            {loading ? "Refreshing…" : "Refresh session"}
          </button>
          {data && <VoiceIndicator voice={data.voice} />}
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
            <EntityPanel entities={data.entities} />
            <CustodyCard custody={data.custody} />
          </div>
        </div>
      ) : (
        <div className="grid h-[452px] animate-pulse place-items-center rounded-card border border-line bg-card text-[11px] text-muted">
          Attaching to scam session…
        </div>
      )}

      <div className="mt-5 border-t border-line pt-3.5 text-[10.5px] leading-relaxed text-muted">
        Agent stays <b className="text-white/60">strictly reactive &amp; victim-framed</b>{" "}
        — never initiates fraud, accesses systems, or redistributes data (clear
        of entrapment + UU ITE Arts. 30/32/33). Extracted wallet flows straight
        into the Investigation graph.
      </div>
    </div>
  );
}
