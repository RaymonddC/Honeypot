/**
 * Animated call waveform — CSS-only scaleY bars (transform, not height, for
 * paint performance). Deterministic pseudo-random heights so SSR and client
 * render identically. `prefers-reduced-motion` → bars render static
 * (globals.css kills the hp-wave animation).
 */

const TONE_CLASS: Record<string, string> = {
  accent: "bg-accent-bright",
  danger: "bg-risk-high",
  neutral: "bg-white/40",
};

export function Waveform({
  active,
  tone = "accent",
  bars = 24,
  className = "",
}: {
  /** Bars animate + brighten while this speaker is talking. */
  active: boolean;
  tone?: "accent" | "danger" | "neutral";
  bars?: number;
  className?: string;
}) {
  const color = TONE_CLASS[tone] ?? TONE_CLASS.accent;
  return (
    <div
      aria-hidden
      className={`flex h-8 items-center justify-center gap-[3px] ${className}`}
    >
      {Array.from({ length: bars }, (_, i) => {
        // Deterministic organic-looking profile (no Math.random → no
        // hydration mismatch).
        const h = 22 + Math.abs(Math.sin(i * 1.7) * 62 + Math.sin(i * 0.6) * 14);
        return (
          <span
            key={i}
            className={`w-[3px] rounded-full ${color} ${
              active ? "hp-wave-bar" : ""
            } transition-opacity duration-300`}
            style={{
              height: `${Math.min(96, h)}%`,
              opacity: active ? 1 : 0.28,
              animationDelay: `${(i % 9) * 0.08}s`,
              animationDuration: `${0.7 + (i % 5) * 0.13}s`,
            }}
          />
        );
      })}
    </div>
  );
}
