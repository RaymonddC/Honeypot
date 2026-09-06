import type { Config } from "tailwindcss";

// ITTU design tokens — corporate/neutral redesign (2026-09). Colors resolve
// through CSS custom properties holding "R G B" channels (see app/globals.css)
// so Tailwind's opacity modifiers (bg-accent/15, border-line/60, ...) keep
// working — a plain var(--x) hex/rgb string can't be sliced by /NN, only a
// channel triple fed through rgb(var(--x) / <alpha-value>) can.
// darkMode: "class" flips the .dark ancestor for the toggle.
function withOpacity(variable: string) {
  return ({ opacityValue }: { opacityValue?: string }) =>
    opacityValue !== undefined
      ? `rgb(var(${variable}) / ${opacityValue})`
      : `rgb(var(${variable}))`;
}

const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // Tailwind's runtime accepts a function per color (it calls back with
      // { opacityValue } to support bg-accent/15 etc.), but @types/tailwindcss
      // only types this map as strings — hence the cast. See withOpacity()
      // above for what actually runs.
      colors: {
        bg: withOpacity("--bg-rgb"),
        sidebar: withOpacity("--sidebar-rgb"),
        card: withOpacity("--card-rgb"),
        elevated: withOpacity("--elevated-rgb"),
        line: withOpacity("--border-rgb"),
        fg: withOpacity("--fg-rgb"),
        muted: withOpacity("--fg-muted-rgb"),
        accent: {
          DEFAULT: withOpacity("--accent-rgb"),
          bright: withOpacity("--accent-bright-rgb"),
        },
        risk: {
          low: withOpacity("--risk-low-rgb"),
          med: withOpacity("--risk-med-rgb"),
          high: withOpacity("--risk-high-rgb"),
        },
      } as unknown as Record<string, string>,
      borderRadius: {
        card: "0.625rem",
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
