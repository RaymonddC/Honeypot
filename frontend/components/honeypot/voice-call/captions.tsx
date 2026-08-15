"use client";

/**
 * Live call captions — the transcript revealed line-by-line, synced to the
 * speech (the call view advances `currentIndex` per spoken line). The log is
 * `aria-live="polite"` so screen readers announce each new caption; inline
 * `◇ extracted` badges appear the moment a line is "heard".
 */

import { useEffect, useRef } from "react";
import { formatConf } from "@/lib/honeypot/types";
import type { VoiceLine } from "@/lib/honeypot/voice";
import type { CallState } from "./call-view";
import { ProviderBadge } from "./provider-badge";
import { Waveform } from "./waveform";

function CaptionLine({
  line,
  speaking,
  provider,
}: {
  line: VoiceLine;
  speaking: boolean;
  /** The TTS provider that actually voiced this line, once it has played. */
  provider?: string;
}) {
  const isPersona = line.speaker === "persona";
  return (
    <div
      className={`hp-fade-up max-w-[78%] rounded-xl border px-3 py-[9px] text-xs leading-relaxed ${
        isPersona
          ? "self-end rounded-br-[4px] border-accent/[.22] bg-accent/10 text-fg"
          : "self-start rounded-bl-[4px] border-line bg-elevated"
      } ${speaking ? (isPersona ? "border-accent/50" : "border-white/20") : ""}`}
    >
      <div
        className={`mb-[3px] flex items-center gap-2 text-[9.5px] uppercase tracking-[.06em] ${
          isPersona ? "text-accent-bright opacity-90" : "opacity-60"
        }`}
      >
        {line.who}
        {speaking && (
          <Waveform
            active
            bars={5}
            tone={isPersona ? "accent" : "neutral"}
            className="!h-3"
          />
        )}
        {provider && (
          <span className="ml-auto normal-case">
            <ProviderBadge provider={provider} />
          </span>
        )}
      </div>
      {line.text}
      {line.extractions.map((ex) => (
        <div
          key={`${line.id}-${ex.label}`}
          className="mt-[7px] flex items-center gap-1.5 border-t border-dashed border-accent/[.22] pt-[7px] font-mono text-[10px] text-accent-bright"
        >
          ◇ extracted · {ex.label} · conf {formatConf(ex.confidence)}
        </div>
      ))}
    </div>
  );
}

export function Captions({
  lines,
  currentIndex,
  state,
  interim = null,
  emptyNote,
  providerByLine,
}: {
  lines: VoiceLine[];
  currentIndex: number;
  state: CallState;
  /** Live-mic mode: the operator's not-yet-final transcript (ghost bubble). */
  interim?: { who: string; text: string } | null;
  /** Live-mic mode: replaces the idle placeholder copy. */
  emptyNote?: string;
  /** line id → the TTS provider that voiced it (recorded after each line plays). */
  providerByLine?: Record<string, string>;
}) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [currentIndex, interim?.text]);

  const visible = state === "idle" ? [] : lines.slice(0, currentIndex + 1);

  return (
    <div
      role="log"
      aria-live="polite"
      aria-label="Live call captions"
      className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4"
    >
      {visible.length === 0 && !interim ? (
        <div className="grid flex-1 place-items-center text-center text-[11px] text-muted">
          {state === "idle"
            ? (emptyNote ??
              "Captions appear here as the call is spoken — press Start call to answer.")
            : "Connecting…"}
        </div>
      ) : (
        visible.map((line, i) => (
          <CaptionLine
            key={line.id}
            line={line}
            speaking={i === currentIndex && state === "live"}
            provider={providerByLine?.[line.id]}
          />
        ))
      )}
      {interim && interim.text && (
        <div className="max-w-[78%] self-start rounded-xl rounded-bl-[4px] border border-dashed border-white/15 bg-elevated/60 px-3 py-[9px] text-xs leading-relaxed text-fg/70">
          <div className="mb-[3px] flex items-center gap-2 text-[9.5px] uppercase tracking-[.06em] opacity-60">
            {interim.who} · hearing…
            <Waveform active bars={5} tone="neutral" className="!h-3" />
          </div>
          {interim.text}
        </div>
      )}
      <div ref={endRef} aria-hidden />
    </div>
  );
}
