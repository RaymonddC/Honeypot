/**
 * User Guide — an in-app orientation page: what ITTU is, the four-module
 * investigation flow, a screen-by-screen walkthrough, the POC↔LIVE data posture,
 * and the two engines analysts ask about most (honeypot scenarios + the wallet
 * risk model). Static content only — no API calls, no secrets. Matches the
 * ELSA card shell used across the app (see app/settings/page.tsx).
 */

type Module = {
  glyph: string;
  name: string;
  href: string;
  tagline: string;
  produces: string;
};

const MODULES: Module[] = [
  {
    glyph: "⬡",
    name: "INFILTRATE",
    href: "/honeypot",
    tagline:
      "An AI honeypot persona poses as a scam victim and engages the scammer. Each turn extracts intel (wallets, bank accounts, phones, links), classifies the crime, and clusters a syndicate — every message SHA-256 hash-chained.",
    produces: "Validated wallet & account intel + crime type",
  },
  {
    glyph: "⇌",
    name: "TRACE",
    href: "/bridge",
    tagline:
      "BridgeWatch correlates fiat bank transfers with crypto deposits by amount and time window, then renders the end-to-end money flow as a Sankey — the bridge foreign tools don't cross.",
    produces: "A fiat → QRIS → crypto flow diagram",
  },
  {
    glyph: "◉",
    name: "TAKEDOWN",
    href: "/investigation",
    tagline:
      "Traces a wallet's transaction network (≤3 hops), computes 12 behavioral features, runs an Isolation Forest plus 5 typology detectors, and scores each wallet with plain-language 'Glass Box' reasoning.",
    produces: "A risk-scored wallet network",
  },
  {
    glyph: "⚑",
    name: "UNCOVER",
    href: "/actions",
    tagline:
      "Turns the analysis into real PDFs — account-freeze requests and PPATK-format suspicious-transaction reports — each hashed for custody, plus a multi-agency notification plan.",
    produces: "Court-ready documents + agency notifications",
  },
];

type Screen = {
  glyph: string;
  name: string;
  href: string;
  see: string;
  doWhat: string;
};

const SCREENS: Screen[] = [
  {
    glyph: "⬡",
    name: "Honeypot",
    href: "/honeypot",
    see: "Scam sessions, a hash-chained transcript, extracted entities, and the syndicate profile.",
    doWhat:
      "Start a session, pick one of 3 scenarios, read the chat, confirm or reject entities.",
  },
  {
    glyph: "⇌",
    name: "Bridge View",
    href: "/bridge",
    see: "A Sankey of the money flow (bank → QRIS → crypto), mule accounts, and correlations.",
    doWhat: "Simulate or inspect how a case's funds moved across channels.",
  },
  {
    glyph: "◉",
    name: "Investigation",
    href: "/investigation",
    see: "An interactive wallet graph with per-wallet risk, reasoning, and fired typologies.",
    doWhat: "Enter a wallet, expand hops, click a node to read its risk breakdown.",
  },
  {
    glyph: "⚑",
    name: "Action Panel",
    href: "/actions",
    see: "A document generator for freeze requests and suspicious-transaction reports.",
    doWhat: "Generate a document, review it, then dispatch to the relevant agencies.",
  },
  {
    glyph: "▦",
    name: "Response",
    href: "/response",
    see: "KPI dashboard — funds at risk / frozen, recovery rate, average time-to-freeze.",
    doWhat: "Track outcomes across cases over a chosen time range.",
  },
  {
    glyph: "⚙",
    name: "Control Panel",
    href: "/settings",
    see: "Which POC/LIVE adapter is active per boundary, voice/call preferences.",
    doWhat: "Check the data posture; set analyst-local call options.",
  },
];

const SCENARIOS = [
  {
    name: "Investment scam",
    persona: "Bu Sari · 54 · Bandung",
    discloses: "TRON wallet, BCA mule account, operator phones",
  },
  {
    name: "Judol deposit",
    persona: "Pak Budi · 47 · Surabaya",
    discloses: "Gambling site, WA admin, BCA deposit mule",
  },
  {
    name: "Crypto phishing",
    persona: "Mbak Rina · 28 · Jakarta",
    discloses: "Fake-airdrop site, ETH wallet, seed-phrase probe",
  },
];

/* ── Shared card shell (mirrors settings/page.tsx) ──────────────────────── */

function Card({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-3.5 rounded-card border border-line bg-card">
      <div className="border-b border-line px-3.5 py-3">
        <span className="eyebrow">{title}</span>
      </div>
      <div className="p-3.5">{children}</div>
    </div>
  );
}

function Glyph({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="flex h-7 w-7 flex-none items-center justify-center rounded-md bg-accent/10 text-sm text-accent-bright"
      aria-hidden
    >
      {children}
    </span>
  );
}

/* ── Page ───────────────────────────────────────────────────────────────── */

export default function GuidePage() {
  return (
    <div className="mx-auto max-w-[820px]">
      {/* header */}
      <div className="mb-4">
        <div className="eyebrow mb-1">Orientation</div>
        <h1 className="text-xl font-bold tracking-tight">
          How ITTU works — a quick guide
        </h1>
        <p className="mt-1 max-w-[62ch] text-xs leading-relaxed text-muted">
          ITTU (Infiltrate, Trace, Takedown &amp; Uncover) turns financial-crime
          response from reactive to proactive. Four modules chain into one
          investigation: hunt intel from scammers, trace the money across bank
          and crypto rails, score the wallet network, and generate the legal
          action — every step preserved for court.
        </p>
      </div>

      {/* the four modules */}
      <Card title="The four modules">
        <ul className="space-y-3">
          {MODULES.map((m) => (
            <li key={m.name} className="flex gap-3">
              <Glyph>{m.glyph}</Glyph>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[13px] font-semibold tracking-wide text-fg">
                    {m.name}
                  </span>
                  <a
                    href={m.href}
                    className="text-[11px] text-accent-bright hover:underline"
                  >
                    open →
                  </a>
                </div>
                <p className="mt-0.5 text-[12px] leading-relaxed text-muted">
                  {m.tagline}
                </p>
                <p className="mt-1 text-[11px] text-fg/70">
                  <span className="text-muted">Produces:</span> {m.produces}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </Card>

      {/* the flow */}
      <Card title="The investigation flow">
        <div className="flex flex-wrap items-center gap-2 text-[12px]">
          {MODULES.map((m, i) => (
            <span key={m.name} className="flex items-center gap-2">
              <span className="rounded-md border border-line bg-elevated px-2.5 py-1 font-mono text-[11px] text-fg">
                {m.glyph} {m.name}
              </span>
              {i < MODULES.length - 1 && (
                <span className="text-muted" aria-hidden>
                  →
                </span>
              )}
            </span>
          ))}
        </div>
        <p className="mt-3 text-[12px] leading-relaxed text-muted">
          A scammer chat surfaces a wallet and a mule account. That wallet feeds
          the bridge (fiat ↔ crypto) and the graph (risk scoring); the scored
          targets feed the action panel, which emits the freeze request and
          agency notifications. Everything is custody-hashed from the first
          message to the final document.
        </p>
      </Card>

      {/* screen walkthrough */}
      <Card title="Screen-by-screen">
        <div className="space-y-2.5">
          {SCREENS.map((s) => (
            <div
              key={s.name}
              className="flex gap-3 rounded-lg border border-line bg-elevated px-3 py-2.5"
            >
              <Glyph>{s.glyph}</Glyph>
              <div className="min-w-0 flex-1">
                <a
                  href={s.href}
                  className="text-[13px] font-medium text-fg hover:text-accent-bright"
                >
                  {s.name}
                </a>
                <p className="mt-0.5 text-[11.5px] leading-snug text-muted">
                  <span className="text-fg/60">See:</span> {s.see}
                </p>
                <p className="mt-0.5 text-[11.5px] leading-snug text-muted">
                  <span className="text-fg/60">Do:</span> {s.doWhat}
                </p>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* POC vs LIVE */}
      <Card title="Data posture — POC vs LIVE">
        <p className="text-[12px] leading-relaxed text-muted">
          Every external boundary (the honeypot LLM, blockchain data, bank
          feeds, notifications) sits behind an adapter that runs in one of two
          modes. The badge in the top bar shows the current mode.
        </p>
        <div className="mt-3 grid gap-2.5 sm:grid-cols-2">
          <div className="rounded-lg border border-risk-med/30 bg-risk-med/[.06] p-3">
            <span className="rounded-md border border-risk-med/40 bg-risk-med/10 px-2 py-0.5 font-mono text-[10px] font-bold tracking-widest text-risk-med">
              POC
            </span>
            <p className="mt-2 text-[11.5px] leading-relaxed text-muted">
              The safe default — fully offline, deterministic, no credentials.
              Scripted honeypot replays, blockchain fixtures, synthetic bank
              data. PDFs and custody hashing are <span className="text-fg/80">real</span>;
              notifications go to a mock sink (nothing leaves the system).
            </p>
          </div>
          <div className="rounded-lg border border-accent/30 bg-accent/[.06] p-3">
            <span className="rounded-md border border-accent/40 bg-accent/10 px-2 py-0.5 font-mono text-[10px] font-bold tracking-widest text-accent-bright">
              LIVE
            </span>
            <p className="mt-2 text-[11.5px] leading-relaxed text-muted">
              The same code against real sources — a real LLM, the Tronscan API,
              bank feeds, agency webhooks. Requires explicit config and keys, and
              fails loudly if they are missing rather than silently degrading.
            </p>
          </div>
        </div>
      </Card>

      {/* honeypot scenarios */}
      <Card title="Honeypot scenarios">
        <p className="mb-3 text-[12px] leading-relaxed text-muted">
          The honeypot ships three MVP scam typologies. Start one from the{" "}
          <a href="/honeypot" className="text-accent-bright hover:underline">
            Honeypot
          </a>{" "}
          screen; each replays a full conversation whose disclosed entities are
          validated into court-usable intel.
        </p>
        <div className="space-y-2">
          {SCENARIOS.map((s) => (
            <div
              key={s.name}
              className="grid grid-cols-1 gap-1 rounded-lg border border-line bg-elevated px-3 py-2.5 sm:grid-cols-[9rem_1fr]"
            >
              <div className="text-[12.5px] font-medium text-fg">{s.name}</div>
              <div className="text-[11.5px] text-muted">
                <span className="font-mono text-fg/70">{s.persona}</span>
                <span className="mx-1.5 text-fg/30">·</span>
                discloses {s.discloses}
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* risk model */}
      <Card title="The wallet risk model">
        <p className="text-[12px] leading-relaxed text-muted">
          TAKEDOWN scores each wallet with an unsupervised <span className="text-fg/80">Isolation
          Forest</span> over 12 behavioral features, backed by 5 deterministic
          typology detectors — peeling chain, rapid relay, circular (wash),
          structuring, and fan-out. The model is validated against the{" "}
          <span className="text-fg/80">Elliptic Data Set</span> (203k Bitcoin
          transactions) for ROC-AUC / precision / recall.
        </p>
        <p className="mt-2 text-[11.5px] text-muted">
          The live model card is served at{" "}
          <code className="rounded bg-elevated px-1.5 py-0.5 font-mono text-[11px] text-fg/80">
            GET /api/takedown/model-card
          </code>
          .
        </p>
      </Card>

      <p className="mb-2 mt-1 text-center text-[11px] text-muted">
        Tip: the fastest way to see the full chain is to start a honeypot
        session, then take the disclosed wallet into the Investigation graph.
      </p>
    </div>
  );
}
