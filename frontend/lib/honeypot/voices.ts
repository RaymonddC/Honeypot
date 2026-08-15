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
  /** no_key | http_401 | http_402 | http_404 | http_422 | transport:<Type> | unreachable */
  error?: string;
  /** On success, the synthesized sample to play in that voice. */
  audioBlob?: Blob;
}

/**
 * Test ONE voice ID by a short backend test-synth (GET /api/tts/voice-check):
 * on success returns the AUDIO (a sample line in that voice) so the caller can
 * play it; on failure returns {ok:false, status, error}. `voice` picks the
 * per-speaker sample line. Uses the Text-to-Speech scope the call itself uses,
 * so it works even with a key restricted to TTS. The key stays server-side.
 */
export async function checkElevenLabsVoice(
  voiceId: string,
  voice: "persona" | "scammer" = "persona",
): Promise<VoiceCheckResult> {
  try {
    const res = await apiFetch(
      `/tts/voice-check?voice_id=${encodeURIComponent(voiceId)}&voice=${voice}`,
    );
    const type = res.headers.get("content-type") ?? "";
    if (res.ok && type.startsWith("audio/")) {
      return { ok: true, audioBlob: await res.blob() };
    }
    if (type.includes("json")) {
      const data = (await res.json()) as { ok?: boolean; status?: number; error?: string };
      return { ok: Boolean(data.ok), status: data.status, error: data.error };
    }
    return { ok: false, status: res.status, error: `http_${res.status}` };
  } catch {
    return { ok: false, error: "unreachable" };
  }
}

/**
 * Gemini prebuilt voices (Google AI Studio TTS) — the ~30 named voices, each
 * with its documented characteristic. The style directive in the backend
 * persona adapter does most of the emotional shaping; the voice sets timbre.
 */
export const GEMINI_VOICES: { name: string; tone: string }[] = [
  { name: "Zephyr", tone: "Bright" },
  { name: "Puck", tone: "Upbeat" },
  { name: "Charon", tone: "Informative" },
  { name: "Kore", tone: "Firm" },
  { name: "Fenrir", tone: "Excitable" },
  { name: "Leda", tone: "Youthful" },
  { name: "Orus", tone: "Firm" },
  { name: "Aoede", tone: "Breezy" },
  { name: "Callirrhoe", tone: "Easy-going" },
  { name: "Autonoe", tone: "Bright" },
  { name: "Enceladus", tone: "Breathy" },
  { name: "Iapetus", tone: "Clear" },
  { name: "Umbriel", tone: "Easy-going" },
  { name: "Algieba", tone: "Smooth" },
  { name: "Despina", tone: "Smooth" },
  { name: "Erinome", tone: "Clear" },
  { name: "Algenib", tone: "Gravelly" },
  { name: "Rasalgethi", tone: "Informative" },
  { name: "Laomedeia", tone: "Upbeat" },
  { name: "Achernar", tone: "Soft" },
  { name: "Alnilam", tone: "Firm" },
  { name: "Schedar", tone: "Even" },
  { name: "Gacrux", tone: "Mature" },
  { name: "Pulcherrima", tone: "Forward" },
  { name: "Achird", tone: "Friendly" },
  { name: "Zubenelgenubi", tone: "Casual" },
  { name: "Vindemiatrix", tone: "Gentle" },
  { name: "Sadachbia", tone: "Lively" },
  { name: "Sadaltager", tone: "Knowledgeable" },
  { name: "Sulafat", tone: "Warm" },
];

const GEMINI_VOICE_NAMES = new Set(GEMINI_VOICES.map((v) => v.name));

/** True if `name` is a real Gemini prebuilt voice (empty = "" server default). */
export function isKnownGeminiVoice(name: string): boolean {
  return GEMINI_VOICE_NAMES.has(name.trim());
}

/**
 * Readiness check for Gemini TTS (GET /api/tts/gemini-check): runs a short
 * backend test-synth in the given voice and, on success, returns the AUDIO
 * sample to play; on failure returns {ok:false, status?, error?} so the Control
 * Panel can show a clear reason (no_key | config:… | http_429 quota | http_400
 * invalid voice | http_404 | http_403). `voice` picks the per-role sample line;
 * `voiceName` tests a just-typed prebuilt voice (blank = server default). The
 * key stays server-side.
 */
export async function checkGemini(
  voice: "persona" | "scammer" = "persona",
  voiceName = "",
): Promise<VoiceCheckResult> {
  try {
    const qs = voiceName.trim()
      ? `?voice=${voice}&voice_name=${encodeURIComponent(voiceName.trim())}`
      : `?voice=${voice}`;
    const res = await apiFetch(`/tts/gemini-check${qs}`);
    const type = res.headers.get("content-type") ?? "";
    if (res.ok && type.startsWith("audio/")) {
      return { ok: true, audioBlob: await res.blob() };
    }
    if (type.includes("json")) {
      const data = (await res.json()) as { ok?: boolean; status?: number; error?: string };
      return { ok: Boolean(data.ok), status: data.status, error: data.error };
    }
    return { ok: false, status: res.status, error: `http_${res.status}` };
  } catch {
    return { ok: false, error: "unreachable" };
  }
}
