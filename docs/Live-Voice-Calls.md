# ITTU — Live Voice Calls (design spec)

**Status:** `/honeypot/call` has **two modes, both shipped**: (1) a scripted-replay
*simulation* (transcript spoken by the browser), and (2) a **live interactive mic mode**
(`live-call-view.tsx`) — the browser's Web Speech API does real STT client-side, feeding a
real backend `/turn` → LLM gateway (keyless deterministic persona fallback when no key). So
"Tier B — in-browser live mic, fully free" below is **already built**. This doc specs the
remaining path to **real telephony** (Tier A — a live phone call over PSTN) and the streaming
server-side STT/TTS behind it — that part is still stub/backlog.

## Where we are (P4b, shipped)
The voice honeypot reuses the whole text pipeline; only the transport + audio are
voice-specific, and every boundary is already an adapter stub waiting for a LIVE impl:

| Boundary | POC (shipped) | LIVE (stub → to build) |
|---|---|---|
| `channel_voice` | `VoiceReplayChannelAdapter` (scripted) | `PstnChannelAdapter` — telephony bridge |
| `STTAdapter` | passthrough (transcript given) | `WhisperSTTAdapter` — streaming speech→text |
| `TTSAdapter` | voice-marks (browser speaks) | `Google/Higgsfield/ElevenLabsTTSAdapter` |

**The agent loop, extraction, custody, classifier, and syndicate clustering are
already live and provider-agnostic.** Going live = implement the three stubs + a
real-time media bridge. No rewrite.

## What a real live call requires
A sub-~1s round-trip media loop so it feels human:

```
 Caller's phone ──call──► Telephony (PSTN/SIP) ──audio stream (WS)──► Media bridge (FastAPI WS)
        ▲                                                                   │
        │                                                                   ▼
   TTS audio  ◄── [TTSAdapter live] ◄── agent.run_session ◄── [STTAdapter live] (streaming)
  (streamed back into the call)          (ALREADY BUILT)      (partial transcripts)
```

New pieces: (1) a telephony provider, (2) streaming STT (id-ID), (3) streaming TTS
(id-ID), (4) a **WebSocket media bridge** orchestrating turn-taking + barge-in.

## The real blockers (not the wiring)
1. **Latency & turn-taking** — must stream STT *and* TTS and support barge-in, or the
   persona talks over people / feels robotic. This is the actual engineering.
2. **Legal / authorization** — a honeypot that engages *real suspects* on live calls in
   Indonesia needs **Polri / law-enforcement gating** (lawful recording, engagement,
   evidence chain). Flagged on `PstnChannelAdapter`. This is institutional, not code —
   it's the true gate on production use.
3. **Seeded numbers** — you don't get organic scam calls on day one; honeypot numbers
   are seeded/advertised.

## Is there a free option? — yes, two tiers

### Tier A — "a real phone actually rings" (near-free)
Provider free trials give enough to demo an **outbound call to your own phone** where
the AI talks + listens — same pipeline, **no legal gate** (you're calling yourself):
- **Twilio** free trial: ~$15 credit + a trial number. Calls only to *verified* numbers
  and prepends a "trial account" banner — fine for a demo. Programmable Voice + **Media
  Streams** (WS audio) is the integration.
- **SignalWire** (Twilio-compatible API), **Vonage**, **Telnyx** — similar free trial
  credit; SignalWire is the closest drop-in if Twilio credit runs out.
- Needs: a provider account + number + a publicly reachable WS endpoint (Render gives us
  one). **This is the recommended demo path.**

### Tier B — "fully free, no telephony" (WebRTC in-browser)
Skip PSTN entirely: a **WebRTC in-browser call** — you speak into the mic, it transcribes
live, the AI answers in voice. Real two-way live voice, **zero phone bill**:
- **STT free:** browser **Web Speech API** `SpeechRecognition` (Chrome, id-ID, free) or
  self-hosted **Whisper**.
- **TTS free:** browser SpeechSynthesis (what we ship) or self-hosted **Piper**/**Coqui**
  for a better voice.
- Same `agent.run_session` in the middle. Not a "phone call", but ~90% of the wow with no
  cost and no accounts.

### Voice quality upgrade (independent of telephony) · ✅ code complete (B1, 2026-08-08)
Swapping the robotic browser voice → a natural one is **just `ITTU_TTS_PROVIDER` + a key**,
thanks to the P4b abstraction. The full audio path is now wired end-to-end:
`ElevenLabsTTSAdapter.synthesize()` → **`GET /api/sessions/{id}/audio/{seq}` serves the audio
bytes** (`audio/mpeg`) — previously it synthesized then discarded them, so LIVE audio never
reached the browser — → the frontend `BackendAudioProvider` plays them. Bytes are cached
(`synthesize_line`, bounded LRU) so a replay never re-pays the provider, and a synthesis
failure **degrades** to browser-speech marks so a TTS outage never breaks the call.
**To hear it:** set `ITTU_TTS_PROVIDER=elevenlabs` + `ITTU_ELEVENLABS_API_KEY` on Render and
flip the Control Panel's voice provider. Works in the browser call view *and* any future live
path; keyless POC stays on browser TTS.

## Recommended sequence
1. **Voice-quality upgrade** (ElevenLabs/Google TTS) — small, big wow, no telephony.
2. **Tier-A Twilio demo** — real phone rings, AI converses (needs your Twilio account +
   number + credentials; then implement `PstnChannelAdapter` + streaming STT/TTS + the WS
   media bridge).
3. **Production live** — streaming/barge-in hardening + **Polri authorization** (gated).

## Cost/effort at a glance
| Path | Cost | Effort | Legal gate |
|---|---|---|---|
| Browser sim (today) | free | shipped | none |
| Real-voice TTS upgrade | ~free tier / cheap | S | none |
| WebRTC in-browser live (Tier B) | free | M | none |
| Twilio real-phone demo (Tier A) | free trial | M–L | none (calling self) |
| Production scammer engagement | metered telephony | L | **Polri required** |
