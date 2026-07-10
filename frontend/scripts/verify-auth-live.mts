/**
 * Live field-alignment harness (P5) — runs the real lib/auth client code in
 * Node against the running backend on :8000. Not part of the app bundle.
 *
 *   npx -y tsx scripts/verify-auth-live.mts
 */

// Minimal window shim so lib/http.ts token storage works outside the browser.
const store = new Map<string, string>();
(globalThis as any).window = {
  localStorage: {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  },
  dispatchEvent: () => true,
  addEventListener: () => {},
  removeEventListener: () => {},
};
(globalThis as any).CustomEvent = class {
  constructor(public type: string) {}
};

const { setToken, clearToken, tokenLooksValid, tokenPayload, apiFetch } =
  await import("../lib/http");
const { demoLogin, fetchMe, fetchConfig } = await import("../lib/auth/api");

let failures = 0;
const check = (label: string, ok: boolean, extra = "") => {
  console.log(`${ok ? "✓" : "✗"} ${label}${extra ? ` — ${extra}` : ""}`);
  if (!ok) failures++;
};

// 1. Demo login (the exact client call the LoginForm makes)
const { jwt, me: loginMe } = await demoLogin("bank-bca", "bank-compliance");
check("demoLogin returns a JWT", !!jwt && jwt.split(".").length === 3);
check("JWT passes client validity check", tokenLooksValid(jwt));
const claims = tokenPayload(jwt);
check(
  "JWT claims {sub, agency_id, role, exp}",
  !!claims?.sub && !!claims?.agency_id && claims?.role === "bank-compliance",
);
check(
  "login response hydrates me",
  loginMe?.agency.name === "Bank BCA" && loginMe?.role === "bank-compliance",
  JSON.stringify(loginMe?.user),
);

// 2. /me with the stored Bearer token (what AuthProvider.hydrateMe does)
setToken(jwt);
const me = await fetchMe();
check(
  "fetchMe → user/agency/role normalized",
  !!me.user.name && me.agency.name === "Bank BCA" && me.role === "bank-compliance",
  `${me.user.name} <${me.user.email}> @ ${me.agency.name} · ${me.agency.type}`,
);

// 3. /config drives the MODE badge
const cfg = await fetchConfig();
check(
  "fetchConfig → mode + per-module modes",
  (cfg.mode === "POC" || cfg.mode === "LIVE") &&
    cfg.source === "api" &&
    cfg.modules.length > 0,
  `mode=${cfg.mode} modules=[${cfg.modules.map((m) => `${m.module}:${m.mode}`).join(", ")}]`,
);

// 4. Protected route rejects a missing/garbage token (guard + 401 event path)
clearToken();
const anon = await apiFetch("/auth/me");
check("GET /auth/me without token → 401", anon.status === 401);
setToken("garbage.token.value");
const bad = await apiFetch("/auth/me");
check("GET /auth/me with bad token → 401", bad.status === 401);
clearToken();

// 5. Module endpoints still respond with a real Bearer attached
setToken(jwt);
const metrics = await apiFetch("/metrics/response?range=30d");
check(
  "module call carries Bearer and succeeds",
  metrics.ok,
  `GET /metrics/response → ${metrics.status}`,
);

console.log(failures === 0 ? "\nALL LIVE CHECKS PASSED" : `\n${failures} FAILURES`);
process.exit(failures === 0 ? 0 : 1);
