import type { Config } from "tailwindcss";

// ITTU design tokens — ELSA-anchored (docs/Frontend-Design.md, authoritative).
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#090909",
        sidebar: "#0c0c0c",
        card: "#111214",
        elevated: "#141414",
        line: "rgba(255,255,255,.06)",
        fg: "rgba(255,255,255,.88)",
        muted: "rgba(255,255,255,.34)",
        accent: {
          DEFAULT: "#10b981",
          bright: "#34d399",
        },
        risk: {
          low: "#10b981",
          med: "#f5a524",
          high: "#ef4444",
        },
      },
      borderRadius: {
        card: "0.75rem",
      },
      fontFamily: {
        sans: ["var(--font-ui)"],
        mono: ["var(--font-mono)"],
      },
    },
  },
  plugins: [],
};

export default config;
