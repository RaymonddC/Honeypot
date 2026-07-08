/**
 * Voice-call indicator (visual only — live STT/TTS lands in P4b).
 * Active: red pill with pulsing rec dot (mockup .voice); standby: dimmed.
 */

import type { VoiceStatus } from "@/lib/honeypot/types";

export function VoiceIndicator({ voice }: { voice: VoiceStatus }) {
  return voice.active ? (
    <span className="inline-flex items-center gap-2 rounded-full bg-risk-high/[.13] px-2.5 py-[5px] text-[10.5px] font-semibold text-risk-high">
      <span className="h-[7px] w-[7px] animate-pulse rounded-full bg-risk-high shadow-[0_0_8px_#ef4444]" />
      {voice.label}
    </span>
  ) : (
    <span className="inline-flex items-center gap-2 rounded-full border border-line bg-elevated px-2.5 py-[5px] text-[10.5px] font-semibold text-muted">
      <span className="h-[7px] w-[7px] rounded-full bg-white/20" />
      {voice.label}
    </span>
  );
}
