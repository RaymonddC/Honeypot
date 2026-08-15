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
