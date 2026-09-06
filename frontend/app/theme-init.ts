// Inline pre-hydration theme script (see components/theme/theme-provider.tsx
// for the full contract). Exported as a string and inlined via
// <script dangerouslySetInnerHTML> in app/layout.tsx's <head> — it MUST run
// before first paint, which means it can't be a normal React effect (those
// only run after the browser has already painted once, causing a visible
// flash from the wrong theme to the right one on every load).
//
// Deliberately tiny and dependency-free: this runs before React, Next.js, or
// any bundle has loaded, so it can only use plain DOM APIs.
export const THEME_INIT_SCRIPT = `
(function () {
  try {
    var t = localStorage.getItem("ittu.theme");
    // Dark (Framer near-black canvas) is the default ground. Explicit "light"
    // adds .light; explicit "system" defers to the OS (@media block); anything
    // else — including a first visit with no stored choice — is dark.
    if (t === "light") document.documentElement.classList.add("light");
    else if (t === "system") { /* no class — @media prefers-color-scheme decides */ }
    else document.documentElement.classList.add("dark");
  } catch (e) {}
})();
`;
