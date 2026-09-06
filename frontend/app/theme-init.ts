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
    // Both classes matter, not just "dark": globals.css's system-dark block
    // is scoped :root:not(.light), so an explicit "light" choice needs the
    // .light class present to override a dark OS preference — adding only
    // "dark" (and never "light") would leave a light choice unable to beat
    // a dark system setting. See theme-provider.tsx's applyTheme() for the
    // same logic running after hydration.
    if (t === "dark") document.documentElement.classList.add("dark");
    else if (t === "light") document.documentElement.classList.add("light");
  } catch (e) {}
})();
`;
