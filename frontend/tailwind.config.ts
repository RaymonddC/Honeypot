import type { Config } from "tailwindcss";

// ITTU design tokens (see app/globals.css). Colors resolve through CSS custom
// properties holding "R G B" channels so Tailwind's opacity modifiers
// (bg-accent/15, border-line/60, ...) keep working — a plain var(--x) hex/rgb
// string can't be sliced by /NN, only a channel triple fed through
// rgb(var(--x) / <alpha-value>) can.
//
// No darkMode strategy is configured: ITTU ships a single dark palette, so
// there is no second theme for a `dark:` variant to switch to (there are zero
// `dark:` utilities in the codebase). See the note atop globals.css.
function withOpacity(variable: string) {
  return ({ opacityValue }: { opacityValue?: string }) =>
    opacityValue !== undefined
      ? `rgb(var(${variable}) / ${opacityValue})`
      : `rgb(var(${variable}))`;
}

const config: Config = {
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
        // Text/icons that sit ON --accent (a white pill).
        "on-accent": withOpacity("--on-accent-rgb"),
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
      },
    },
  },
  plugins: [],
};

export default config;
