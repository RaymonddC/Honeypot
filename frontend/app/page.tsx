import Link from "next/link";

/**
 * ITTU marketing landing — the public front door (renders bare, no app shell;
 * see components/auth/app-gate.tsx PUBLIC_ROUTES). Built to the Framer-style
 * dark-canvas design system: near-black ground, oversized white display type
 * with aggressive negative tracking, a single blue accent reserved for links,
 * white pill CTAs, and vibrant gradient spotlight cards as the atmosphere device.
 */

const C = {
  canvas: "#090909",
  surface1: "#141414",
  surface2: "#1c1c1c",
  hairline: "#262626",
  ink: "#ffffff",
  muted: "#999999",
  blue: "#0099ff",
  violet: "#6a4cf5",
  magenta: "#d44df0",
  orange: "#ff7a3d",
  coral: "#ff5577",
} as const;

// Extreme negative tracking is the brand signature (scales with size).
const display = (size: string, tracking: string): React.CSSProperties => ({
  fontSize: size,
  fontWeight: 600,
  lineHeight: 0.92,
  letterSpacing: tracking,
});

function PillPrimary({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center justify-center rounded-full px-5 py-2.5 text-sm font-medium transition-transform active:scale-95"
      style={{ background: C.ink, color: C.canvas, letterSpacing: "-0.14px" }}
    >
      {children}
    </Link>
  );
}

function PillSecondary({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center justify-center rounded-full px-5 py-2.5 text-sm font-medium transition-colors hover:brightness-125"
      style={{ background: C.surface1, color: C.ink, letterSpacing: "-0.14px" }}
    >
      {children}
    </Link>
  );
}

const PILLARS = [
  {
    tag: "01",
    name: "Infiltrate",
    ground: C.violet,
    line: "An AI honeypot poses as the victim, baits the scammer, and extracts the receiving accounts and wallets — before anyone files a report.",
    produces: "Validated account & wallet intel",
  },
  {
    tag: "02",
    name: "Trace",
    ground: C.magenta,
    line: "A correlation engine links the fiat money to its crypto on-ramp by amount and time, and renders the whole flow as a Sankey.",
    produces: "Fiat → crypto money map",
  },
  {
    tag: "03",
    name: "Takedown",
    ground: C.orange,
    line: "The wallet's network is mapped and scored — with plain-language reasoning for every risk call. No black box.",
    produces: "Risk-scored wallet network",
  },
  {
    tag: "04",
    name: "Uncover",
    ground: C.coral,
    line: "One click turns the analysis into an official freeze request and STR — hash-chained for custody, dispatched to every agency at once.",
    produces: "Court-ready documents",
  },
];

const FLOW = [
  ["Log in", "Agency-scoped access — each institution sees only its own data."],
  ["Run the honeypot", "Extract the mule account + collection wallet from the scammer."],
  ["Freeze fast", "Generate & dispatch the block request — the 30-minute window."],
  ["Trace & take down", "Follow the money across rails; score the wallet network."],
  ["File & recover", "STR to PPATK, multi-agency alert, evidence bundle — all hashed."],
];

export default function Landing() {
  return (
    <div style={{ background: C.canvas, color: C.ink }} className="min-h-screen antialiased">
      {/* ── top nav ─────────────────────────────────────────────────── */}
      <header
        className="sticky top-0 z-50 flex h-14 items-center justify-between px-5 backdrop-blur sm:px-8"
        style={{ background: "rgba(9,9,9,.72)", borderBottom: `1px solid ${C.hairline}` }}
      >
        <div className="flex items-center gap-2">
          <span
            className="flex h-6 w-6 items-center justify-center rounded-md font-mono text-xs font-bold"
            style={{ background: "rgba(255,255,255,.1)", color: C.ink }}
          >
            IT
          </span>
          <span className="text-sm font-semibold tracking-tight">ITTU</span>
        </div>
        <nav className="hidden items-center gap-7 text-sm md:flex" style={{ color: C.muted }}>
          <a href="#problem" className="transition-colors hover:text-white">Problem</a>
          <a href="#pillars" className="transition-colors hover:text-white">Platform</a>
          <a href="#flow" className="transition-colors hover:text-white">How it works</a>
          <a href="#trust" className="transition-colors hover:text-white">Security</a>
        </nav>
        <div className="flex items-center gap-2">
          <PillSecondary href="/login">Sign in</PillSecondary>
          <PillPrimary href="/login">Try the demo</PillPrimary>
        </div>
      </header>

      {/* ── hero ────────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-[1200px] px-5 pb-24 pt-20 sm:px-8 sm:pt-28">
        <div
          className="mb-6 inline-flex items-center gap-2 rounded-full px-3 py-1 text-[13px]"
          style={{ background: C.surface1, color: C.muted, letterSpacing: "-0.13px" }}
        >
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: C.blue }} />
          Financial-crime forensics · Indonesia
        </div>
        <h1
          className="max-w-[16ch] text-balance"
          style={display("clamp(2.75rem, 8.5vw, 6.875rem)", "-0.05em")}
        >
          From a scam report to a frozen account — in minutes, not days.
        </h1>
        <p
          className="mt-7 max-w-[52ch] text-[18px] leading-relaxed"
          style={{ color: C.muted, letterSpacing: "-0.18px" }}
        >
          ITTU hunts the money before it disappears — an AI honeypot, a fiat↔crypto
          tracer, an explainable wallet-risk engine, and one-click legal action, in a
          single case file.
        </p>
        <div className="mt-9 flex flex-wrap items-center gap-3">
          <PillPrimary href="/login">Try the demo →</PillPrimary>
          <a
            href="#flow"
            className="text-sm font-medium transition-colors hover:brightness-125"
            style={{ color: C.blue, letterSpacing: "-0.14px" }}
          >
            See how it works
          </a>
        </div>

        {/* stat strip */}
        <div
          className="mt-16 grid grid-cols-2 gap-px overflow-hidden rounded-2xl sm:grid-cols-4"
          style={{ background: C.hairline }}
        >
          {[
            ["Rp 7.8T", "lost to online scams / yr*"],
            ["< 5%", "of funds ever recovered"],
            ["> 12h", "average time to freeze — today"],
            ["< 30 min", "with ITTU"],
          ].map(([v, l], i) => (
            <div key={l} className="p-5" style={{ background: C.surface1 }}>
              <div
                className="font-mono tabular-nums"
                style={{ ...display("clamp(1.5rem,3vw,2rem)", "-0.03em"), color: i === 3 ? C.blue : C.ink }}
              >
                {v}
              </div>
              <div className="mt-1 text-[13px]" style={{ color: C.muted }}>{l}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ── problem ─────────────────────────────────────────────────── */}
      <section id="problem" className="mx-auto max-w-[1200px] px-5 py-24 sm:px-8">
        <div className="text-[13px] font-medium uppercase tracking-widest" style={{ color: C.muted }}>
          The threats you can&apos;t see
        </div>
        <h2 className="mt-4 max-w-[20ch]" style={display("clamp(2rem,5.5vw,3.875rem)", "-0.045em")}>
          Suspicious money hides in the noise. Old tools just display it.
        </h2>
        <p className="mt-6 max-w-[60ch] text-[18px] leading-relaxed" style={{ color: C.muted, letterSpacing: "-0.18px" }}>
          Dirty rupiah jumps from a bank account to QRIS to a crypto exchange in minutes —
          across five agencies that don&apos;t share a platform, using foreign forensic
          tools that don&apos;t understand local typologies. By the time a victim reports,
          the trail is gone.
        </p>
      </section>

      {/* ── pillars (gradient spotlight cards) ──────────────────────── */}
      <section id="pillars" className="mx-auto max-w-[1200px] px-5 py-8 sm:px-8">
        <h2 className="mb-10 max-w-[16ch]" style={display("clamp(2rem,5vw,3.875rem)", "-0.045em")}>
          Four moves. One case file.
        </h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {PILLARS.map((p) => (
            <div
              key={p.name}
              className="relative overflow-hidden p-8"
              style={{
                borderRadius: 30,
                background: `linear-gradient(150deg, ${p.ground} 0%, ${p.ground}cc 55%, #0a0a0a 140%)`,
              }}
            >
              <div className="font-mono text-[13px] opacity-70">{p.tag}</div>
              <div className="mt-1" style={display("2rem", "-0.02em")}>{p.name}</div>
              <p className="mt-4 max-w-[42ch] text-[15px] leading-relaxed" style={{ letterSpacing: "-0.15px" }}>
                {p.line}
              </p>
              <div className="mt-6 inline-flex items-center gap-2 rounded-full bg-black/25 px-3 py-1 text-[12px] font-medium backdrop-blur">
                ↳ {p.produces}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── flow ────────────────────────────────────────────────────── */}
      <section id="flow" className="mx-auto max-w-[1200px] px-5 py-24 sm:px-8">
        <div className="text-[13px] font-medium uppercase tracking-widest" style={{ color: C.muted }}>
          How it works
        </div>
        <h2 className="mt-4 max-w-[18ch]" style={display("clamp(2rem,5vw,3.875rem)", "-0.045em")}>
          One identity, from bait to freeze.
        </h2>
        <ol className="mt-12 divide-y" style={{ borderColor: C.hairline }}>
          {FLOW.map(([title, desc], i) => (
            <li key={title} className="flex flex-col gap-2 py-6 sm:flex-row sm:items-baseline sm:gap-8" style={{ borderColor: C.hairline }}>
              <div className="flex w-16 flex-none items-baseline gap-3">
                <span className="font-mono text-[13px]" style={{ color: C.blue }}>0{i + 1}</span>
              </div>
              <div className="flex-none sm:w-56" style={display("1.5rem", "-0.02em")}>{title}</div>
              <p className="text-[16px] leading-relaxed" style={{ color: C.muted, letterSpacing: "-0.16px" }}>{desc}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* ── trust / security ────────────────────────────────────────── */}
      <section id="trust" className="mx-auto max-w-[1200px] px-5 py-8 sm:px-8">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {[
            ["Court-ready by design", "Every message, score, and document is SHA-256 hash-chained into a custody trail (UU ITE Ps. 5)."],
            ["Explainable, not black-box", "Isolation Forest + 5 deterministic typology detectors, each risk call shown in plain language."],
            ["Human-gated action", "Documents are drafts; outward dispatch takes a two-step confirm. Nothing fires on one click."],
          ].map(([t, d]) => (
            <div key={t} className="p-6" style={{ background: C.surface1, borderRadius: 20, border: `1px solid ${C.hairline}` }}>
              <div style={display("1.375rem", "-0.02em")}>{t}</div>
              <p className="mt-3 text-[15px] leading-relaxed" style={{ color: C.muted, letterSpacing: "-0.15px" }}>{d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── closing CTA ─────────────────────────────────────────────── */}
      <section className="mx-auto max-w-[1200px] px-5 py-28 text-center sm:px-8">
        <h2 className="mx-auto max-w-[18ch]" style={display("clamp(2.5rem,7vw,5.25rem)", "-0.05em")}>
          Hunt the money. Before it&apos;s gone.
        </h2>
        <div className="mt-9 flex justify-center">
          <PillPrimary href="/login">Try the demo →</PillPrimary>
        </div>
      </section>

      {/* ── footer ──────────────────────────────────────────────────── */}
      <footer className="px-5 py-12 sm:px-8" style={{ borderTop: `1px solid ${C.hairline}` }}>
        <div className="mx-auto flex max-w-[1200px] flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
          <div className="flex items-center gap-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-md font-mono text-xs font-bold" style={{ background: "rgba(255,255,255,.1)" }}>IT</span>
            <span className="text-sm font-semibold tracking-tight">ITTU</span>
            <span className="text-[13px]" style={{ color: C.muted }}>· Infiltrate · Trace · Takedown · Uncover</span>
          </div>
          <div className="text-[12px]" style={{ color: C.muted }}>
            * Figures indicative, from public reporting — verify against IASC/OJK before citing.
          </div>
        </div>
      </footer>
    </div>
  );
}
