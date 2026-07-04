# ITTU — Frontend Design (design system + screens)

> Anchored on **ELSA's real shipped theme** (extracted from `elsa/frontend/src/index.css` — the
> authoritative source; ELSA's `tailwind.config.js` has an *aspirational* gold/purple theme that is
> NOT what's implemented — ignore it). Interactive mockup of all 5 surfaces:
> **https://claude.ai/code/artifact/d592d92c-de21-45f8-b609-ab88e7fd8661** (nav or press 1–5).

## Design tokens (from ELSA `index.css` — real values)
| Token | Value | Use |
|---|---|---|
| `--background` | `#090909` | app ground (near-black) |
| `--sidebar` | `#0c0c0c` | left rail |
| `--card` | `#111111` | cards/panels |
| `--secondary/muted/accent` | `#141414` | inputs, chips, elevated fills |
| `--foreground` | `rgba(255,255,255,.85)` | text (muted .35–.7) |
| **accent (emerald)** | `#10b981` / `#34d399` | primary accent, links, active nav |
| teal / cyan / sky / blue | `#14b8a6` `#06b6d4` `#0ea5e9` `#3b82f6` | chart + graph/Sankey ramp |
| `--border` | `rgba(255,255,255,.06)` | hairline borders |
| `--destructive` | `#ef4444` | danger |
| `--radius` | `0.75rem` | card radius |
| fonts | **Inter** (UI) · **JetBrains Mono** (data/addresses/amounts) | — |

**Semantic risk colors** (separate from the emerald accent): low `#10b981` · med `#f5a524` ·
high `#ef4444`. Use tabular-nums for all figures. Section eyebrows = 10px uppercase, `.06–.09em`
letter-spacing (ELSA's `prose-elsa h2` pattern). Thin 6px scrollbars. Aesthetic: sleek "linear.app /
terminal" dark forensics console.

> Mockup note: the Artifact uses **system-ui + ui-monospace** stand-ins because Artifacts can't
> CDN-link fonts. The **real app uses Inter + JetBrains Mono** (ELSA already vendors these).

## App shell
- **Left module rail:** Investigation · Bridge View · Action Panel · Response · Honeypot (+ intel group).
- **Top bar:** case switcher (`#ITU-2026-xxxx`), agency context chip, **POC/LIVE mode badge**, user.
- **Main canvas:** per-screen. Multi-agency context is always visible (RLS-backed).

## Screens (reuse ELSA components where noted)
1. **Investigation** — wallet search → Cytoscape graph (risk-colored nodes, amount-sized edges,
   highlighted peeling-chain path) · wallet detail card w/ risk gauge + 12 features · fired patterns ·
   **Glass Box reasoning trace** (reuse ELSA `ReasoningPanel`).
2. **Bridge View** — D3 `d3-sankey` (QRIS→mule→exchange→USDT→foreign) · suspected-on-ramp feed
   (confidence-ranked) · mule-network stats · split fiat│bridge│crypto.
3. **Action Panel** — 3 generated docs (freeze PDF · goAML LTKM draft · multi-agency alert) ·
   human-gated dispatch with POC=mock status.
4. **Response Dashboard** — metric tiles (time-to-freeze, recovery rate) · trend sparkline · cases table.
5. **Honeypot** — chat transcript w/ inline entity extraction · extracted-entities panel (confidence) ·
   chain-of-custody · voice-call indicator (text + voice).

## Component inventory (port from ELSA `frontend/src/components`)
`ui/` primitives (button, card, badge, input, dialog, separator, Toast, LoadingSkeleton — shadcn/Radix
+ CVA) · `ReasoningPanel` (Glass Box) · `WalletDashboardCard` · `ChatPanel`/`ChatSidebar` shell ·
`TransactionChart` (hand-SVG). New builds: graph canvas (Cytoscape.js), Sankey (d3-sankey), Action
Panel, metric tiles, honeypot console.

## Approach decision
- **Design direction** iterated here with Claude (this mockup = reference). 
- **Implementation** delegated to the **Frontend teammate agent** at build time — Next.js 16 + shadcn
  (skills: `nextjs-shadcn`, `ui-ux-pro-max`), porting ELSA's real components + this design system.
- Accessibility: visible focus rings (present in ELSA), semantic risk not color-only (pair with
  label/pill), `prefers-reduced-motion` respected.

## Open
- Confirm design direction (see mockup) before build.
- Decide graph lib final: Cytoscape.js (planned) vs Sigma.js fallback above ~5k nodes.
