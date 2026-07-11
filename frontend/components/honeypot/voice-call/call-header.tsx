/**
 * Call header — caller card (unknown caller + suspected scam line), mode tag,
 * on-call state pill (reuses VoiceIndicator) and the running call timer.
 */

import { VoiceIndicator } from "@/components/honeypot/voice-indicator";
import type { CallState } from "./call-view";

const STATE_LABEL: Record<CallState, string> = {
  idle: "Voice · ready",
  live: "On call · agent live",
  paused: "Call on hold",
  takeover: "On call · analyst live",
  ended: "Call ended",
};

function formatTimer(totalSec: number): string {
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function PhoneIncomingIcon() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-4.5 w-4.5"
      style={{ width: 18, height: 18 }}
    >
      <polyline points="16 2 16 8 22 8" />
      <line x1="23" y1="1" x2="16" y2="8" />
      <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" />
    </svg>
  );
}

export function CallHeader({
  callerId,
  persona,
  modeTag,
  state,
  elapsed,
}: {
  callerId: string;
  persona: string;
  modeTag: string;
  state: CallState;
  elapsed: number;
}) {
  const onAir = state === "live" || state === "takeover";
  const timer = formatTimer(elapsed);

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
      {/* caller card */}
      <div className="flex min-w-0 items-center gap-3">
        <div
          aria-hidden
          className={`grid h-10 w-10 flex-none place-items-center rounded-full border ${
            onAir
              ? "border-risk-high/40 bg-risk-high/10 text-risk-high"
              : "border-line bg-elevated text-muted"
          }`}
        >
          <PhoneIncomingIcon />
        </div>
        <div className="min-w-0">
          <div className="truncate font-mono text-[13px] font-semibold text-fg">
            {callerId}
          </div>
          <small className="block truncate text-[10.5px] text-muted">
            unknown caller · suspected scam line · persona &ldquo;{persona}
            &rdquo; answering
          </small>
        </div>
      </div>

      {/* state + timer */}
      <div className="flex flex-none items-center gap-2">
        <span className="rounded-md border border-line bg-elevated px-2 py-0.5 font-mono text-[10.5px] text-white/60">
          {modeTag}
        </span>
        <VoiceIndicator voice={{ active: onAir, label: STATE_LABEL[state] }} />
        <span
          role="timer"
          aria-label={`Call time ${timer}`}
          className={`rounded-md border border-line bg-elevated px-2.5 py-0.5 font-mono text-[13px] font-semibold tnum ${
            onAir ? "text-accent-bright" : "text-muted"
          }`}
        >
          {timer}
        </span>
      </div>
    </div>
  );
}
