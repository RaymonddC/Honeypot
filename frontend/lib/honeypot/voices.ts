/**
 * ElevenLabs voice lookup — GET /api/tts/voices (backend proxies the key
 * server-side; the browser only ever sees voice id + name). Powers the Control
 * Panel's "Check voices" button: flag a persona/scammer voice ID that isn't in
 * the operator's ElevenLabs library BEFORE a call falls back to the browser.
 */

import { apiFetch } from "@/lib/http";

export interface ElevenLabsVoice {
  id: string;
  name: string;
}

export interface VoicesResult {
  /** True when an ElevenLabs key is configured server-side. */
  configured: boolean;
  voices: ElevenLabsVoice[];
  /** Short reason when the lookup failed (bad key / unreachable). */
  error: string | null;
}

export async function fetchElevenLabsVoices(): Promise<VoicesResult> {
  try {
    const res = await apiFetch("/tts/voices");
    if (!res.ok) {
      return { configured: false, voices: [], error: `http_${res.status}` };
    }
    const data = (await res.json()) as {
      configured?: boolean;
      voices?: ElevenLabsVoice[];
      error?: string | null;
    };
    return {
      configured: Boolean(data.configured),
      voices: Array.isArray(data.voices) ? data.voices : [],
      error: data.error ?? null,
    };
  } catch {
    return { configured: false, voices: [], error: "unreachable" };
  }
}

export interface VoiceCheckResult {
  ok: boolean;
  status?: number;
  /** no_key | http_401 | http_404 | http_422 | transport:<Type> | unreachable */
  error?: string;
}

/**
 * Validate ONE voice ID by a tiny backend test-synth (GET /api/tts/voice-check).
 * Uses the Text-to-Speech scope the call itself uses, so it works even with a
 * key restricted to TTS (unlike listing voices). The key stays server-side.
 */
export async function checkElevenLabsVoice(voiceId: string): Promise<VoiceCheckResult> {
  try {
    const res = await apiFetch(`/tts/voice-check?voice_id=${encodeURIComponent(voiceId)}`);
    if (!res.ok) return { ok: false, status: res.status, error: `http_${res.status}` };
    const data = (await res.json()) as VoiceCheckResult;
    return {
      ok: Boolean(data.ok),
      status: data.status,
      error: data.error,
    };
  } catch {
    return { ok: false, error: "unreachable" };
  }
}
