"use client";

/**
 * Tier-B LIVE-MIC call view (docs/Live-Voice-Calls.md · WebRTC-free tier).
 * The OPERATOR plays the scammer: Web Speech `SpeechRecognition` (id-ID,
 * continuous+interim) transcribes the mic → POST /sessions/{id}/turn → the
 * persona replies → spoken through the same `VoiceProvider` interface as the
 * scripted view — captions, waveform and entity pop-ins all update live.
 *
 * Degradations, all graceful:
 *   - no SpeechRecognition (Safari/Firefox) → notice + text-input fallback
 *   - mic permission denied → notice + text-input fallback
 *   - backend unreachable / no interactive support → local mock persona
 *     (rule-based Bu Sari with regex extraction) so the demo runs standalone
 *   - barge-in: the operator talking cancels persona speech mid-line
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useCases } from "@/components/cases/case-provider";
import { CustodyCard } from "@/components/honeypot/custody-card";
import { EntityPanel } from "@/components/honeypot/entity-panel";
import {
  buildMockLiveCall,
  mockLiveReply,
  postLiveTurn,
  startLiveCall,
} from "@/lib/honeypot/live";
import { MicTranscriber, sttSupported } from "@/lib/honeypot/stt";
import { createVoiceProvider, type VoiceProvider } from "@/lib/honeypot/tts";
import type { DataSource } from "@/lib/honeypot/types";
import {
  estimateDurationSec,
  type VoiceCallSession,
  type VoiceEntity,
  type VoiceLine,
} from "@/lib/honeypot/voice";
import { CallHeader } from "./call-header";
import type { CallState } from "./call-view";
import { Captions } from "./captions";
import { Waveform } from "./waveform";

type LiveState = "idle" | "connecting" | "live" | "ended";
type MicStatus = "unsupported" | "denied" | "muted" | "on";

const OPERATOR_WHO = "Operator · scam caller";

/* ── Icons (lucide paths, stroke currentColor) ─────────────────────────── */

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

const MicIcon = () => (
  <Icon>
    <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
    <line x1="12" x2="12" y1="19" y2="22" />
  </Icon>
);

const MicOffIcon = () => (
  <Icon>
    <line x1="2" x2="22" y1="2" y2="22" />
    <path d="M18.89 13.23A7.12 7.12 0 0 0 19 12v-2" />
    <path d="M5 10v2a7 7 0 0 0 12 5" />
    <path d="M15 9.34V5a3 3 0 0 0-5.68-1.33" />
    <path d="M9 9v3a3 3 0 0 0 5.12 2.12" />
    <line x1="12" x2="12" y1="19" y2="22" />
  </Icon>
);

const PhoneCallIcon = () => (
  <Icon>
    <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" />
  </Icon>
);

const PhoneOffIcon = () => (
  <Icon>
    <path d="M10.68 13.31a16 16 0 0 0 3.41 2.6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7 2 2 0 0 1 1.72 2v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.42 19.42 0 0 1-3.33-2.67m-2.67-3.34a19.79 19.79 0 0 1-3.07-8.63A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91" />
    <line x1="22" x2="2" y1="2" y2="22" />
  </Icon>
);

const SendIcon = () => (
  <Icon>
    <path d="m22 2-7 20-4-9-9-4Z" />
    <path d="M22 2 11 13" />
  </Icon>
);

const BASE_BTN =
  "inline-flex h-11 cursor-pointer items-center gap-2 rounded-full px-5 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40";

/* ── Speaker stage tile (mirrors call-view) ────────────────────────────── */

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

export function LiveCallView({
  onSourceChange,
}: {
  /** Bubbles the api/mock source up to the page badge once connected. */
  onSourceChange?: (source: DataSource | null) => void;
}) {
  const { activeCaseId } = useCases();
  const [state, setState] = useState<LiveState>("idle");
  const [call, setCall] = useState<VoiceCallSession | null>(null);
  const [lines, setLines] = useState<VoiceLine[]>([]);
  const [entities, setEntities] = useState<VoiceEntity[]>([]);
  const [custodyNote, setCustodyNote] = useState<string | null>(null);
  const [interim, setInterim] = useState("");
  const [micStatus, setMicStatus] = useState<MicStatus>("muted");
  const [personaSpeaking, setPersonaSpeaking] = useState(false);
  const [speakingLineId, setSpeakingLineId] = useState<string | null>(null);
  const [thinking, setThinking] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [textDraft, setTextDraft] = useState("");

  const stateRef = useRef(state);
  stateRef.current = state;
  const callRef = useRef(call);
  callRef.current = call;
  const linesRef = useRef(lines);
  linesRef.current = lines;
  const personaSpeakingRef = useRef(false);

  const providerRef = useRef<VoiceProvider | null>(null);
  const sttRef = useRef<MicTranscriber | null>(null);
  /** Bumping this kills in-flight loops (end call / new call / unmount). */
  const runIdRef = useRef(0);
  const busyRef = useRef(false);
  const queueRef = useRef<string[]>([]);
  const localSeqRef = useRef(1000); // local line ids never collide with api seqs
  const turnCountRef = useRef(0);

  /* ── helpers ── */

  const appendLines = useCallback((next: VoiceLine[]) => {
    setLines((prev) => [...prev, ...next]);
  }, []);

  const nextOffset = (): number => {
    const last = linesRef.current[linesRef.current.length - 1];
    return last ? last.offsetSec + last.durationSec : 0;
  };

  const speakLine = useCallback(async (line: VoiceLine, runId: number) => {
    const provider = providerRef.current;
    if (!provider || runIdRef.current !== runId) return;
    personaSpeakingRef.current = true;
    setPersonaSpeaking(true);
    setSpeakingLineId(line.id);
    try {
      await provider.speak(line);
    } finally {
      personaSpeakingRef.current = false;
      if (runIdRef.current === runId) {
        setPersonaSpeaking(false);
        setSpeakingLineId(null);
      }
    }
  }, []);

  /** Operator heard while the persona is talking → cut the persona off. */
  const bargeIn = useCallback(() => {
    if (personaSpeakingRef.current) {
      providerRef.current?.cancel();
      personaSpeakingRef.current = false;
      setPersonaSpeaking(false);
      setSpeakingLineId(null);
    }
  }, []);

  /* ── turn round-trip ── */

  const submitTurn = useCallback(
    async (text: string) => {
      const clean = text.trim();
      const session = callRef.current;
      if (!clean || !session || stateRef.current !== "live") return;
      if (busyRef.current) {
        queueRef.current.push(clean); // finish the current turn first
        return;
      }
      busyRef.current = true;
      const runId = runIdRef.current;
      bargeIn();

      // 1 — the operator's line lands immediately (their own words).
      const seq = ++localSeqRef.current;
      const operatorLine: VoiceLine = {
        id: `op-${seq}`,
        seq,
        speaker: "scammer",
        who: OPERATOR_WHO,
        text: clean,
        durationSec: estimateDurationSec(clean),
        offsetSec: nextOffset(),
        extractions: [],
        disclosure: false,
      };
      appendLines([operatorLine]);
      setThinking(true);

      // 2 — persona reply: backend agent loop, local persona as fallback.
      let personaLine: VoiceLine | null = null;
      let turnEntities: VoiceEntity[] = [];
      let operatorExtractions: VoiceLine["extractions"] = [];
      if (session.source === "api") {
        try {
          const turn = await postLiveTurn(
            session.id,
            session.persona,
            clean,
            operatorLine.offsetSec,
          );
          personaLine = turn.persona;
          turnEntities = turn.entities;
          operatorExtractions = turn.operator?.extractions ?? [];
        } catch {
          /* backend turn failed mid-call → local persona keeps it alive */
        }
      }
      if (!personaLine) {
        const local = mockLiveReply(clean, turnCountRef.current);
        const replySeq = ++localSeqRef.current;
        personaLine = {
          id: `pr-${replySeq}`,
          seq: replySeq,
          speaker: "persona",
          who: `Honeypot · ${session.persona.split(",")[0].trim()}`,
          text: local.reply,
          durationSec: estimateDurationSec(local.reply),
          offsetSec: operatorLine.offsetSec + operatorLine.durationSec,
          extractions: [],
          disclosure: false,
        };
        operatorExtractions = local.extractions.map((e) => ({
          label: e.label,
          confidence: e.confidence,
        }));
        turnEntities = local.extractions.map((e, i) => ({
          id: `live-e-${seq}-${i}`,
          type: e.type,
          value: e.value,
          subtitle: e.subtitle,
          confidence: e.confidence,
          reviewStatus: "unverified",
          revealAtLine: 0,
        }));
      }
      turnCountRef.current += 1;
      if (runIdRef.current !== runId) {
        busyRef.current = false;
        return; // call ended/restarted while the turn was in flight
      }

      // 3 — reveal: extraction badges on the operator line, entities → panel.
      if (operatorExtractions.length) {
        setLines((prev) =>
          prev.map((l) =>
            l.id === operatorLine.id
              ? { ...l, extractions: operatorExtractions, disclosure: true }
              : l,
          ),
        );
      }
      if (turnEntities.length) {
        setEntities((prev) => {
          const known = new Set(prev.map((e) => `${e.type}:${e.value}`));
          const fresh = turnEntities.filter(
            (e) => !known.has(`${e.type}:${e.value}`),
          );
          return [...prev, ...fresh];
        });
      }
      setThinking(false);
      appendLines([personaLine]);
      setCustodyNote(null); // recomputed from line count below

      // 4 — speak the reply (barge-in can cancel it), then drain the queue.
      await speakLine(personaLine, runId);
      busyRef.current = false;
      const queued = queueRef.current.shift();
      if (queued && runIdRef.current === runId) void submitTurn(queued);
    },
    [appendLines, bargeIn, speakLine],
  );

  /* ── mic ── */

  const startMic = useCallback(() => {
    if (!sttSupported()) {
      setMicStatus("unsupported");
      setNotice(
        "Speech recognition is not available in this browser (Safari/Firefox) — type as the scammer below instead.",
      );
      return;
    }
    const stt = (sttRef.current ??= new MicTranscriber({
      lang: "id-ID",
      onInterim: setInterim,
      onFinal: (text) => {
        setInterim("");
        void submitTurn(text);
      },
      onSpeechStart: bargeIn,
      onError: (kind, message) => {
        if (kind === "permission") {
          setMicStatus("denied");
          setNotice(
            "Microphone permission denied — allow mic access or type as the scammer below.",
          );
        } else if (kind === "audio") {
          setMicStatus("denied");
          setNotice("No microphone found — type as the scammer below.");
        } else if (kind === "unsupported") {
          // Persistent network failure = STT unusable here → text fallback.
          setMicStatus("unsupported");
          setNotice(
            message ||
              "Live speech isn't available in this browser — type as the scammer below.",
          );
        } else if (kind === "network") {
          setNotice("Reconnecting to the speech service…");
        }
      },
      onListeningChange: (listening) => {
        setMicStatus((prev) =>
          prev === "denied" || prev === "unsupported"
            ? prev
            : listening
              ? "on"
              : "muted",
        );
      },
    }));
    stt.start();
  }, [bargeIn, submitTurn]);

  const toggleMic = () => {
    if (micStatus === "on") {
      sttRef.current?.stop();
      setInterim("");
    } else {
      if (micStatus === "denied") setNotice(null);
      setMicStatus("muted"); // clear denied so onListeningChange can flip it on
      startMic();
    }
  };

  /* ── call lifecycle ── */

  const handleStart = useCallback(async () => {
    const runId = ++runIdRef.current;
    setState("connecting");
    setLines([]);
    setEntities([]);
    setElapsed(0);
    setNotice(null);
    onSourceChange?.(null);
    const session = await startLiveCall(activeCaseId);
    if (runIdRef.current !== runId) return;

    setCall(session);
    onSourceChange?.(session.source);
    providerRef.current = createVoiceProvider(session.id);
    setLines(session.lines);
    turnCountRef.current = 0;
    queueRef.current = [];
    busyRef.current = false;
    setState("live");
    startMic();
    // Persona answers the phone (greeting line(s), if any).
    for (const line of session.lines) {
      if (line.speaker !== "persona") continue;
      await speakLine(line, runId);
      if (runIdRef.current !== runId) return;
    }
  }, [onSourceChange, speakLine, startMic, activeCaseId]);

  const handleEnd = () => {
    runIdRef.current++;
    providerRef.current?.cancel();
    sttRef.current?.stop();
    setInterim("");
    setThinking(false);
    setPersonaSpeaking(false);
    setSpeakingLineId(null);
    setState("ended");
  };

  const handleTextSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!textDraft.trim()) return;
    void submitTurn(textDraft);
    setTextDraft("");
  };

  // Call timer.
  useEffect(() => {
    if (state !== "live") return;
    const t = setInterval(() => setElapsed((v) => v + 1), 1000);
    return () => clearInterval(t);
  }, [state]);

  // Full teardown on unmount.
  useEffect(
    () => () => {
      runIdRef.current++;
      providerRef.current?.cancel();
      sttRef.current?.stop();
    },
    [],
  );

  /* ── render mapping ── */

  const personaFirst = (call?.persona ?? "Bu Sari, 54").split(",")[0].trim();
  const speakingIndex = speakingLineId
    ? lines.findIndex((l) => l.id === speakingLineId)
    : -1;
  const captionState: CallState =
    state === "idle"
      ? "idle"
      : state === "ended"
        ? "ended"
        : personaSpeaking && speakingIndex >= 0
          ? "live"
          : "takeover"; // full transcript visible, no speaking highlight
  const currentIndex =
    personaSpeaking && speakingIndex >= 0 ? speakingIndex : lines.length - 1;

  const headerState: CallState =
    state === "live" ? "live" : state === "ended" ? "ended" : "idle";

  const statusLine =
    state === "idle"
      ? "Tier-B live call — you play the scammer on the mic; the AI persona answers"
      : state === "connecting"
        ? "dialing… starting interactive session"
        : state === "ended"
          ? "call ended · transcript sealed in custody log"
          : thinking
            ? "persona thinking… agent loop running on your turn"
            : personaSpeaking
              ? "persona speaking — talk to barge in"
              : micStatus === "on"
                ? "listening (id-ID) — speak as the scammer"
                : "mic muted — unmute or type below";

  const custody = call
    ? {
        ...call.custody,
        messagesLogged:
          custodyNote ??
          `${lines.length}${call.custody.intact ? " · hash-chained" : ""}`,
      }
    : null;

  return (
    <div className="grid grid-cols-1 items-start gap-3.5 lg:grid-cols-[1fr_300px]">
      {/* ── The call ─────────────────────────────────────────────────── */}
      <div className="flex h-[calc(100vh-13.5rem)] min-h-[480px] flex-col rounded-card border border-line bg-card">
        <CallHeader
          callerId={call?.callerId ?? "live mic · operator"}
          persona={call?.persona ?? "Bu Sari, 54"}
          modeTag={call?.modeTag ?? "Tier-B · live mic"}
          state={headerState}
          elapsed={elapsed}
        />

        {/* speaker stage */}
        <div className="grid grid-cols-2 gap-3 border-b border-line p-4">
          <SpeakerTile
            label="Operator (scammer role)"
            sub={
              micStatus === "on"
                ? "live mic · listening"
                : micStatus === "unsupported"
                  ? "text input · no STT"
                  : micStatus === "denied"
                    ? "text input · mic blocked"
                    : "mic muted"
            }
            active={interim.length > 0}
            tone="danger"
          />
          <SpeakerTile
            label={`Honeypot · ${personaFirst}`}
            sub="AI persona · agent loop"
            active={personaSpeaking}
            tone="accent"
          />
        </div>

        <Captions
          lines={lines}
          currentIndex={currentIndex}
          state={captionState}
          interim={interim ? { who: OPERATOR_WHO, text: interim } : null}
          emptyNote="Start the live call, then speak as the scammer — the AI persona answers in voice and the transcript appears here."
        />

        {/* ── live controls ── */}
        <div className="border-t border-line px-4 py-3">
          {notice && (
            <p
              role="status"
              className="mb-2.5 rounded-lg border border-risk-med/30 bg-risk-med/10 px-3 py-2 text-center text-[11px] text-risk-med"
            >
              {notice}
            </p>
          )}

          <div className="flex flex-wrap items-center justify-center gap-2.5">
            {(state === "idle" || state === "connecting") && (
              <button
                type="button"
                onClick={() => void handleStart()}
                disabled={state === "connecting"}
                className={`${BASE_BTN} border border-accent/40 bg-accent/15 text-accent-bright hover:bg-accent/25`}
              >
                <PhoneCallIcon />
                {state === "connecting" ? "Dialing…" : "Start live call"}
              </button>
            )}

            {state === "live" && (
              <>
                <button
                  type="button"
                  onClick={toggleMic}
                  disabled={micStatus === "unsupported"}
                  aria-pressed={micStatus === "on"}
                  title={
                    micStatus === "unsupported"
                      ? "SpeechRecognition unavailable — use the text field"
                      : micStatus === "on"
                        ? "Mute the mic"
                        : "Unmute the mic"
                  }
                  className={`${BASE_BTN} ${
                    micStatus === "on"
                      ? "border border-risk-high/40 bg-risk-high/10 text-risk-high hover:bg-risk-high/20"
                      : "border border-line bg-elevated text-fg hover:bg-white/[.07]"
                  }`}
                >
                  {micStatus === "on" ? <MicIcon /> : <MicOffIcon />}
                  {micStatus === "on" ? "Mic live" : "Mic muted"}
                </button>
                <button
                  type="button"
                  onClick={handleEnd}
                  className={`${BASE_BTN} border border-risk-high/40 bg-risk-high/10 text-risk-high hover:bg-risk-high/20`}
                >
                  <PhoneOffIcon /> End call
                </button>
              </>
            )}

            {state === "ended" && (
              <button
                type="button"
                onClick={() => void handleStart()}
                className={`${BASE_BTN} border border-accent/40 bg-accent/15 text-accent-bright hover:bg-accent/25`}
              >
                <PhoneCallIcon /> Start new call
              </button>
            )}
          </div>

          {state === "live" && (
            <form
              onSubmit={handleTextSubmit}
              className="mx-auto mt-2.5 flex max-w-md items-center gap-2"
            >
              <label htmlFor="live-turn-input" className="sr-only">
                Type as the scammer
              </label>
              <input
                id="live-turn-input"
                value={textDraft}
                onChange={(e) => setTextDraft(e.target.value)}
                placeholder={
                  micStatus === "on"
                    ? "…or type as the scammer"
                    : "Type as the scammer (mic off)"
                }
                autoComplete="off"
                className="h-9 min-w-0 flex-1 rounded-lg border border-line bg-elevated px-3 text-xs text-fg placeholder:text-muted"
              />
              <button
                type="submit"
                disabled={!textDraft.trim() || thinking}
                aria-label="Send turn"
                className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-lg border border-accent/40 bg-accent/15 px-3 text-xs font-semibold text-accent-bright transition-colors hover:bg-accent/25 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <SendIcon /> Send
              </button>
            </form>
          )}

          <div
            role="status"
            className="mt-2.5 flex items-center justify-center gap-2 text-[11px] text-muted"
          >
            <span className="text-accent-bright" aria-hidden>
              ◇
            </span>
            {statusLine}
          </div>
        </div>
      </div>

      {/* ── Side rail — reused console panels ────────────────────────── */}
      <div>
        <EntityPanel entities={entities} />
        {custody && <CustodyCard custody={custody} />}
        <p className="mt-3 px-1 text-[10.5px] leading-relaxed text-muted">
          Entities are extracted live from what you say on the call —{" "}
          <b className="text-white/60">{entities.length}</b> so far. Disclosed
          wallets/accounts feed the Investigation graph.
        </p>
      </div>
    </div>
  );
}
