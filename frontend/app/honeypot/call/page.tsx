"use client";

/**
 * Voice honeypot — dedicated full-screen call view (P4b + Tier-B live-mic).
 * Two interchangeable modes, both speaking through the same `VoiceProvider`
 * abstraction (lib/honeypot/tts.ts) and reusing captions/waveform/entity
 * panels:
 *
 *   scripted   CallView   — the AI persona replays a pre-run agent-loop
 *                            transcript (POST /api/sessions {channel_type:
 *                            "voice"}); falls back to the local mock call.
 *   live-mic   LiveCallView — Tier-B interactive: the operator plays the
 *                            scammer over the mic (Web Speech API), the
 *                            persona answers turn-by-turn (docs/Live-Voice-
 *                            Calls.md). Falls back to a local rule-based
 *                            persona when the backend has no /turn support.
 *
 * The mode is the analyst's Control Panel `callMode` setting (lib/settings.ts)
 * — the header toggle here is the same single source of truth, just handier
 * than opening /settings before every call.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { CallView } from "@/components/honeypot/voice-call/call-view";
import { LiveCallView } from "@/components/honeypot/voice-call/live-call-view";
import type { DataSource } from "@/lib/honeypot/types";
import { fetchVoiceCall, type VoiceCallSession } from "@/lib/honeypot/voice";
import { useSettings, type CallModeSetting } from "@/lib/settings";

export default function HoneypotCallPage() {
  const t = useTranslations("honeypot.callPage");
  const MODE_LABEL: Record<CallModeSetting, string> = {
    scripted: t("modeScripted"),
    "live-mic": t("modeLiveMic"),
  };
  const { settings, update } = useSettings();
  const mode = settings.callMode;

  const [data, setData] = useState<VoiceCallSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [liveSource, setLiveSource] = useState<DataSource | null>(null);
  const loadSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++loadSeq.current;
    setLoading(true);
    const result = await fetchVoiceCall();
    if (seq !== loadSeq.current) return; // superseded
    setData(result);
    setLoading(false);
  }, []);

  // Only the scripted mode needs a pre-run session fetched up front — the
  // live-mic mode starts its own session on "Start live call".
  useEffect(() => {
    if (mode === "scripted") void load();
  }, [mode, load]);

  const source = mode === "scripted" ? data?.source : liveSource;

  return (
    <div className="mx-auto max-w-[1200px]">
      {/* ── header ─────────────────────────────────────────────────── */}
      <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link
            href="/honeypot"
            className="text-[12px] text-muted transition-colors hover:text-fg"
          >
            {t("backLink")}
          </Link>
          <h1 className="text-xl font-bold tracking-tight">
            {t("title")}{" "}
            <span className="font-semibold text-muted">{t("titleModule")}</span>
          </h1>
          <p className="mt-1 max-w-[52ch] text-[12px] text-muted">
            {mode === "scripted" ? t("descScripted") : t("descLiveMic")}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <div
            role="radiogroup"
            aria-label={t("callModeLabel")}
            className="flex rounded-lg border border-line bg-elevated p-0.5"
          >
            {(["scripted", "live-mic"] as const).map((m) => (
              <button
                key={m}
                type="button"
                role="radio"
                aria-checked={mode === m}
                onClick={() => update({ callMode: m })}
                title={
                  m === "scripted"
                    ? t("modeScriptedTitle")
                    : t("modeLiveMicTitle")
                }
                className={`cursor-pointer rounded-md px-2.5 py-1 text-[12px] font-semibold transition-colors ${
                  mode === m
                    ? "bg-accent/15 text-accent-bright"
                    : "text-muted hover:text-fg"
                }`}
              >
                {MODE_LABEL[m]}
              </button>
            ))}
          </div>

          {source && (
            <span
              className={`rounded-md border px-2 py-0.5 font-mono text-[12px] font-semibold ${
                source === "api"
                  ? "border-accent/30 bg-accent/10 text-accent-bright"
                  : "border-risk-med/30 bg-risk-med/10 text-risk-med"
              }`}
              title={
                source === "api"
                  ? t("liveApiTitle")
                  : t("offlineMockTitle")
              }
            >
              {source === "api" ? t("liveApi") : t("offlineMock")}
            </span>
          )}
        </div>
      </div>

      {mode === "live-mic" ? (
        <LiveCallView onSourceChange={setLiveSource} />
      ) : data && !loading ? (
        <CallView data={data} />
      ) : (
        <div className="grid h-[calc(100vh-13.5rem)] min-h-[480px] animate-pulse place-items-center rounded-card border border-line bg-card text-[12px] text-muted">
          {t("dialing")}
        </div>
      )}
    </div>
  );
}
