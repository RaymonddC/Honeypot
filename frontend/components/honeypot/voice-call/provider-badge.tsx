"use client";

/**
 * Per-line TTS provider badge — shows which voice ACTUALLY played a line:
 * a real provider (ElevenLabs / Gemini / Google) or the browser fallback
 * (which means the chosen provider failed or has no key). Fed by
 * `VoiceProvider.lastProvider`.
 */

import { useTranslations } from "next-intl";

const PROVIDER_COLOR: Record<string, string> = {
  elevenlabs: "#0099ff", // emerald — real natural voice
  gemini: "#a78bfa", // violet
  google: "#33adff", // cyan
  browser: "#f5a524", // amber — fell back, NOT the real provider
};

export function ProviderBadge({ provider }: { provider: string }) {
  const t = useTranslations("honeypot.voiceCall.providerBadge");
  const color = PROVIDER_COLOR[provider] ?? "rgba(255,255,255,.5)";
  return (
    <span
      className="inline-flex items-center gap-0.5 rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-semibold leading-none"
      style={{ color, borderColor: `${color}44`, background: `${color}14` }}
      title={
        provider === "browser"
          ? t("browserTitle")
          : t("voicedByTitle", { provider })
      }
    >
      🔊 {provider}
    </span>
  );
}
