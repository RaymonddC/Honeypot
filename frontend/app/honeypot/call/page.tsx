"use client";

/**
 * Voice honeypot — dedicated full-screen call view (P4b). The AI persona
 * answers the scam call: browser TTS speaks the lines (VoiceProvider
 * abstraction — env-swappable to backend audio), captions reveal in sync,
 * entities pop into the reused panel as they're heard. Starts a voice
 * session via POST /api/sessions {channel_type:"voice"}; falls back to the
 * local voice-framed mock when the backend is unreachable.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { CallView } from "@/components/honeypot/voice-call/call-view";
import { fetchVoiceCall, type VoiceCallSession } from "@/lib/honeypot/voice";

export default function HoneypotCallPage() {
  const [data, setData] = useState<VoiceCallSession | null>(null);
  const [loading, setLoading] = useState(true);
  const loadSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++loadSeq.current;
    setLoading(true);
    const result = await fetchVoiceCall();
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
          <Link
            href="/honeypot"
            className="text-[11px] text-muted transition-colors hover:text-fg"
          >
            ← Honeypot console
          </Link>
          <h1 className="text-xl font-bold tracking-tight">
            Voice call{" "}
            <span className="font-semibold text-muted">· INFILTRATE</span>
          </h1>
          <p className="mt-1 text-xs text-muted">
            The AI persona answers the scam call live — STT → agent loop → TTS
            — entities extracted as they&apos;re spoken, chain-of-custody
            logged.
          </p>
        </div>
        {data && (
          <span
            className={`rounded-md border px-2 py-0.5 font-mono text-[10.5px] font-semibold ${
              data.source === "api"
                ? "border-accent/30 bg-accent/10 text-accent-bright"
                : "border-risk-med/30 bg-risk-med/10 text-risk-med"
            }`}
            title={
              data.source === "api"
                ? "Live backend API — voice session started on demand"
                : "Backend unreachable — rendering local demo call"
            }
          >
            {data.source === "api" ? "● live api" : "● offline · mock"}
          </span>
        )}
      </div>

      {data && !loading ? (
        <CallView data={data} />
      ) : (
        <div className="grid h-[calc(100vh-13.5rem)] min-h-[480px] animate-pulse place-items-center rounded-card border border-line bg-card text-[11px] text-muted">
          Dialing scam line… starting voice session
        </div>
      )}
    </div>
  );
}
