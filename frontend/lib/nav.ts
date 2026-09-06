/**
 * Route matching for navigation state.
 *
 * Lives here rather than in components/app-shell.tsx because the case context
 * bar needs it too, and app-shell already imports that — importing back would
 * be a cycle.
 */

/**
 * Is `href` the navigation entry for the page at `pathname`?
 *
 * A bare `pathname.startsWith(href)` is wrong whenever one route is a string
 * prefix of another: "/honeypot-ops".startsWith("/honeypot") is true, so
 * browsing Honeypot Ops lit up BOTH it and "① Infiltrate" in the rail, and the
 * navigation stopped answering "where am I". Matching whole path segments fixes
 * that while still marking a parent active for its children — /honeypot/call
 * keeps /honeypot highlighted, which is the behaviour that wanted `startsWith`
 * in the first place.
 */
export function isNavActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}
