"use client";

/**
 * Voice-call view orchestrator (P4b).
 *
 * Drives the call line-by-line through the `VoiceProvider` INTERFACE (never
 * `speechSynthesis` directly — lib/honeypot/tts.ts selects the provider from
 * NEXT_PUBLIC_VOICE_PROVIDER): reveals captions in sync with the speech,
 * animates the active speaker's waveform, pops entities into the reused
 * EntityPanel as each line is "heard", and arms the human-in-the-loop
 * "Take over" (barge-in) control at the disclosure turn.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { CustodyCard } from "@/components/honeypot/custody-card";
import { EntityPanel } from "@/components/honeypot/entity-panel";
import { createVoiceProvider, type VoiceProvider } from "@/lib/honeypot/tts";
import type { VoiceCallSession } from "@/lib/honeypot/voice";
import { CallControls } from "./call-controls";
import { CallHeader } from "./call-header";
import { Captions } from "./captions";
import { Waveform } from "./waveform";

export type CallState = "idle" | "live" | "paused" | "takeover" | "ended";

/* ── Speaker stage tile ────────────────────────────────────────────────── */

function SpeakerTile({
  label,
  sub,
  active,
  tone,
}: {
  label: string;
  sub: string;
  active: boolean;
  tone: "accent" | "danger";
}) {
  return (
    <div
      className={`rounded-xl border px-4 py-3 transition-colors duration-300 ${
        active
          ? tone === "accent"
            ? "border-accent/40 bg-accent/[.07]"
            : "border-risk-high/40 bg-risk-high/[.06]"
          : "border-line bg-elevated/50"
      }`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span
          className={`truncate text-[10px] font-semibold uppercase tracking-[.06em] ${
            active
              ? tone === "accent"
                ? "text-accent-bright"
                : "text-risk-high"
              : "text-muted"
          }`}
        >
          {label}
        </span>
        <small className="hidden flex-none text-[9.5px] text-muted sm:block">
          {sub}
        </small>
      </div>
      <Waveform
        active={active}
        tone={active ? (tone === "accent" ? "accent" : "danger") : "neutral"}
        className="mt-2"
      />
    </div>
  );
}

/* ── Orchestrator ──────────────────────────────────────────────────────── */

export function CallView({ data }: { data: VoiceCallSession }) {
  const t = useTranslations("honeypot.voiceCall.callView");
  const [state, setState] = useState<CallState>("idle");
  const [currentIndex, setCurrentIndex] = useState(-1);
  const [elapsed, setElapsed] = useState(0);
  // Which provider actually voiced each line (by line id, set after it plays) → captions badge.
  const [providerByLine, setProviderByLine] = useState<Record<string, string>>({});

  const stateRef = useRef(state);
  stateRef.current = state;
  const providerRef = useRef<VoiceProvider | null>(null);
  /** Bumping this kills any in-flight playback loop (restart/takeover). */
  const runIdRef = useRef(0);
  const resumeWaitersRef = useRef<Array<() => void>>([]);

  const flushResumeWaiters = () => {
    const waiters = resumeWaitersRef.current;
    resumeWaitersRef.current = [];
    waiters.forEach((w) => w());
  };

  /** Blocks the loop while paused (covers pauses landing between lines). */
  const waitIfPaused = (): Promise<void> =>
    stateRef.current === "paused"
      ? new Promise<void>((resolve) => resumeWaitersRef.current.push(resolve))
      : Promise.resolve();

  const playFrom = useCallback(
    async (start: number) => {
      const provider = (providerRef.current ??= createVoiceProvider(data.id));
      const runId = ++runIdRef.current;
      setState("live");
      for (let i = start; i < data.lines.length; i++) {
        if (runIdRef.current !== runId) return;
        setCurrentIndex(i);
        await provider.speak(data.lines[i]);
        if (runIdRef.current !== runId) return;
        const played = provider.lastProvider;
        setProviderByLine((m) => ({ ...m, [data.lines[i].id]: played }));
        await waitIfPaused();
        if (runIdRef.current !== runId) return;
      }
      setState("ended");
    },
    [data],
  );

  const handleStart = () => {
    setElapsed(0);
    void playFrom(0);
  };

  const handlePause = () => {
    setState("paused");
    providerRef.current?.pause();
  };

  const handleResume = () => {
    setState("live");
    providerRef.current?.resume();
    flushResumeWaiters();
  };

  const handleRestart = () => {
    runIdRef.current++; // kill the current loop
    providerRef.current?.cancel();
    flushResumeWaiters();
    setElapsed(0);
    setCurrentIndex(-1);
    setProviderByLine({});
    void playFrom(0);
  };

  /** Barge-in: mute the agent mid-line, analyst takes the call. */
  const handleTakeOver = () => {
    runIdRef.current++;
    providerRef.current?.cancel();
    flushResumeWaiters();
    setState("takeover");
  };

  const handleHandBack = () => {
    void playFrom(Math.min(currentIndex + 1, data.lines.length));
  };

  // Running call timer (keeps counting during analyst takeover — the call is
  // still live; holds while paused).
  useEffect(() => {
    if (state !== "live" && state !== "takeover") return;
    const t = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(t);
  }, [state]);

  // Stop speech when the view unmounts.
  useEffect(
    () => () => {
      runIdRef.current++;
      providerRef.current?.cancel();
    },
    [],
  );

  const currentLine = currentIndex >= 0 ? data.lines[currentIndex] : null;
  const speaking = state === "live" && currentLine != null;
  const personaFirst = data.persona.split(",")[0].trim();

  // Entities pop in as each line is "heard".
  const heardEntities =
    state === "idle"
      ? []
      : data.entities.filter((e) => e.revealAtLine <= currentIndex);

  const takeoverArmed =
    data.disclosureIndex >= 0
      ? currentIndex >= data.disclosureIndex
      : currentIndex >= 0;

  return (
    <div className="grid grid-cols-1 items-start gap-3.5 lg:grid-cols-[1fr_300px]">
      {/* ── The call ─────────────────────────────────────────────────── */}
      <div className="flex h-[calc(100vh-13.5rem)] min-h-[480px] flex-col rounded-card border border-line bg-card">
        <CallHeader
          callerId={data.callerId}
          persona={data.persona}
          modeTag={data.modeTag}
          state={state}
          elapsed={elapsed}
        />

        {/* speaker stage */}
        <div className="grid grid-cols-2 gap-3 border-b border-line p-4">
          <SpeakerTile
            label={t("scammerLabel")}
            sub={data.callerId}
            active={speaking && currentLine?.speaker === "scammer"}
            tone="danger"
          />
          <SpeakerTile
            label={t("personaLabel", { persona: personaFirst })}
            sub={t("personaSub")}
            active={speaking && currentLine?.speaker === "persona"}
            tone="accent"
          />
        </div>

        <Captions
          lines={data.lines}
          currentIndex={currentIndex}
          state={state}
          providerByLine={providerByLine}
        />

        <CallControls
          state={state}
          takeoverArmed={takeoverArmed}
          onStart={handleStart}
          onPause={handlePause}
          onResume={handleResume}
          onRestart={handleRestart}
          onTakeOver={handleTakeOver}
          onHandBack={handleHandBack}
        />
      </div>

      {/* ── Side rail — reused console panels ────────────────────────── */}
      <div>
        <EntityPanel entities={heardEntities} />
        <CustodyCard custody={data.custody} />
        <p className="mt-3 px-1 text-[10.5px] leading-relaxed text-muted">
          {t.rich("entitiesNote", {
            heard: heardEntities.length,
            total: data.entities.length,
            b: (chunks) => <b className="text-fg">{chunks}</b>,
          })}
        </p>
      </div>
    </div>
  );
}
