"use client";

/**
 * Call controls — Start / Pause / Resume / Restart plus the human-in-the-loop
 * "Take over" (barge-in), which arms at the disclosure turn and mutes the
 * agent while the analyst is on the line. All targets ≥44px, icon+label,
 * focus-visible rings from globals.css.
 */

import { useTranslations } from "next-intl";
import type { CallState } from "./call-view";

/* ── Inline SVG icons (lucide paths, stroke currentColor) ──────────────── */

function Icon({ children }: { children: React.ReactNode }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ width: 14, height: 14 }}
    >
      {children}
    </svg>
  );
}

const PhoneIcon = () => (
  <Icon>
    <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" />
  </Icon>
);

const PauseIcon = () => (
  <Icon>
    <rect x="6" y="4" width="4" height="16" rx="1" />
    <rect x="14" y="4" width="4" height="16" rx="1" />
  </Icon>
);

const PlayIcon = () => (
  <Icon>
    <polygon points="6 3 20 12 6 21 6 3" />
  </Icon>
);

const RestartIcon = () => (
  <Icon>
    <polyline points="1 4 1 10 7 10" />
    <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
  </Icon>
);

const HeadsetIcon = () => (
  <Icon>
    <path d="M3 18v-6a9 9 0 0 1 18 0v6" />
    <path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z" />
  </Icon>
);

/* ── Buttons ───────────────────────────────────────────────────────────── */

const BASE_BTN =
  "inline-flex h-11 cursor-pointer items-center gap-2 rounded-full px-5 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40";

function PrimaryButton(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      {...props}
      className={`${BASE_BTN} border border-accent/40 bg-accent/15 text-accent-bright hover:bg-accent/25`}
    />
  );
}

function NeutralButton(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      {...props}
      className={`${BASE_BTN} border border-line bg-elevated text-fg hover:bg-fg/[.07]`}
    />
  );
}

export function CallControls({
  state,
  takeoverArmed,
  onStart,
  onPause,
  onResume,
  onRestart,
  onTakeOver,
  onHandBack,
}: {
  state: CallState;
  /** True once the disclosure turn has been reached. */
  takeoverArmed: boolean;
  onStart: () => void;
  onPause: () => void;
  onResume: () => void;
  onRestart: () => void;
  onTakeOver: () => void;
  onHandBack: () => void;
}) {
  const t = useTranslations("honeypot.voiceCall.controls");
  const STATUS: Record<CallState, string> = {
    idle: t("statusIdle"),
    live: t("statusLive"),
    paused: t("statusPaused"),
    takeover: t("statusTakeover"),
    ended: t("statusEnded"),
  };
  const onCall = state === "live" || state === "paused";

  return (
    <div className="border-t border-line px-4 py-3">
      <div className="flex flex-wrap items-center justify-center gap-2.5">
        {state === "idle" && (
          <PrimaryButton onClick={onStart}>
            <PhoneIcon /> {t("startCall")}
          </PrimaryButton>
        )}

        {state === "live" && (
          <NeutralButton onClick={onPause}>
            <PauseIcon /> {t("pause")}
          </NeutralButton>
        )}

        {state === "paused" && (
          <PrimaryButton onClick={onResume}>
            <PlayIcon /> {t("resume")}
          </PrimaryButton>
        )}

        {onCall && (
          <button
            type="button"
            onClick={onTakeOver}
            disabled={!takeoverArmed}
            title={
              takeoverArmed
                ? t("takeOverArmedTitle")
                : t("takeOverDisarmedTitle")
            }
            className={`${BASE_BTN} border border-risk-med/40 bg-risk-med/10 text-risk-med hover:bg-risk-med/20 ${
              takeoverArmed ? "animate-pulse" : ""
            }`}
          >
            <HeadsetIcon /> {t("takeOver")}
          </button>
        )}

        {state === "takeover" && (
          <PrimaryButton onClick={onHandBack}>
            <PlayIcon /> {t("handBack")}
          </PrimaryButton>
        )}

        {state === "ended" && (
          <PrimaryButton onClick={onRestart}>
            <RestartIcon /> {t("replayCall")}
          </PrimaryButton>
        )}

        {state !== "idle" && state !== "ended" && (
          <NeutralButton onClick={onRestart}>
            <RestartIcon /> {t("restart")}
          </NeutralButton>
        )}
      </div>

      <div className="mt-2.5 flex items-center justify-center gap-2 text-[11px] text-muted">
        <span className="text-accent-bright" aria-hidden>
          ◇
        </span>
        {STATUS[state]}
      </div>
    </div>
  );
}
