# ITTU — MVP Scope (Hackathon) & Roadmap

> Reconciles Gary's "combine Product 1 + 2 → 4 screens" directive with the ITTU proposal and our
> locked architecture. **Decisions (2026-07-01):** hackathon MVP first → then full product on the same
> foundation; scope = **Gary's 4 screens + the honeypot**; built on the **real architecture, run lean**
> (Postgres + Next 16 + adapter/MODE toggle; **Neo4j deferred**, NetworkX-only for MVP).

---

## Strategy: "real architecture, run lean"

The 4 screens **are the POC** in our POC↔LIVE model. We build them on the real stack so the same
codebase flips toward the full product without a rewrite — NOT on throwaway hackathon infra.

- ✅ Keep: FastAPI modular monolith · **PostgreSQL + RLS** (Docker, one command) · **Next.js 16** +
  shadcn/ui (port ELSA's loved design system + Glass Box) · adapter/**MODE** toggle · **LiteLLM
  gateway** (tiered routing) · Dramatiq + Redis · ReportLab · Cytoscape.js · d3-sankey.
- ⏸️ **Defer Neo4j** — our data model treats it as a *rebuildable projection*, so **NetworkX in-memory**
  for the MVP costs nothing architecturally and matches Gary's "no Neo4j overhead." Add Neo4j when the
  persistent cross-case graph becomes interactive/large (post-hackathon). *(This reverses the earlier
  "Neo4j from start" pick — deliberately.)*
- ➡️ Blockchain via an **adapter**: **TRONSCAN** as MVP primary (Gary's endpoint) + **TronGrid** backup;
  Bitquery/others added later. USDT-TRC20 focus.

---

## Hackathon MVP = 5 deliverables

### Screen 1 — Investigation (module: TAKEDOWN)  ·  ~60% of build effort
Input a TRON wallet → fetch USDT-TRC20 transfers (TRONSCAN `/api/transfer/trc20`) → interactive
**Cytoscape.js** directed graph (force layout; nodes green→yellow→red by risk, edges sized by amount,
arrows = flow). **Multi-hop tracing:** click a node → BFS expand up to 3 hops; highlight source→dest
paths. **ML risk scoring:** the **12 features** (tx freq, volume, unique counterparties, rapid-relay
rate, round-number %, fan-in/out ratio, account age, in/out ratio, time-entropy, chain depth,
self-loop count, max tx) → **Isolation Forest** (scikit-learn, contamination≈0.05) as anomaly triage
+ **rule-based typology overlay** (ported from ELSA). **5 patterns flagged:** peeling chain, rapid
relay (in/out>0.95, <5 min), circular (NetworkX `find_cycle`), structuring/smurfing (similar-amount
clusters), fan-out dispersal (1→10+). Every flag carries **confidence + reasoning** (Glass Box).

### Screen 2 — Bridge View (module: TRACE / BridgeWatch)  ·  visual wow
**D3.js Sankey** of the fiat→crypto pipeline using the **PT A2Z / Oei-Hengky case** as narrative
(4,656 accounts · 22 banks · Rp 530B). Left = **simulated** QRIS deposits + bank mule accounts
(synthetic generator on real case params; PaySim fallback). Right = **real** TRON/USDT data. Middle =
the **bridge**: correlation engine matching fiat aggregation to crypto deposits by **amount (fee
tolerance) + 30-min timing window**. Mule-network detection via NetworkX community detection + DBSCAN.
Split-screen fiat/crypto dashboard + confidence-ranked alert feed.

### Screen 3 — Action Panel (module: UNCOVER)
One click on a confirmed pattern generates: **(a)** account-freeze request **PDF** (ReportLab,
auto-filled: wallets, tx hashes, risk scores, timestamps); **(b)** **LTKM/STR draft** pre-filled for
**PPATK goAML** (subject placeholder, tx details, risk indicators, narrative); **(c)** **multi-agency
alert** (POC = mock sink to bank + exchange + PPATK; LIVE = real dispatch). Documents are hashed
(evidence).

### Screen 4 — Response Dashboard
Metrics view: cases in progress, **avg time-to-freeze**, funds at risk, funds frozen, **recovery
rate** — narrating "days → minutes." Backed by real `cases`/`action_documents` data.

### Deliverable 5 — INFILTRATE Honeypot (text + voice)
Per `docs/INFILTRATE-Design.md`. In near-term scope by user decision (proposal's headline module).
For the hackathon it can run in **POC mode** (replayed transcripts / scripted caller) to demo safely,
with the LIVE channels (Telegram/WhatsApp + voice) architected but gated. Feeds extracted
wallets/accounts straight into Screens 1–2.

---

## How the 5 pieces connect (one story)
Honeypot (5) extracts a scammer's TRON wallet + mule account → Investigation (1) scores & graphs the
wallet, flags a peeling chain → traces to an exchange deposit → Bridge (2) shows the QRIS→mule→crypto
Sankey with the timing-correlated bridge → Action Panel (3) generates the freeze request + goAML LTKM
+ multi-agency alert → Response Dashboard (4) shows time-to-freeze dropping to minutes. **That's the
demo narrative end-to-end.**

---

## Data & narrative sources
- **Crypto (real):** TRONSCAN + TronGrid, USDT-TRC20.
- **ML validation:** Elliptic++ (822k addresses) / Elliptic (204k Bitcoin txs) — for accuracy metrics,
  not applied directly to Indonesian wallets (features are anonymized; compute our own 12).
- **Fiat (simulated):** synthetic generator on PT A2Z params; PaySim fallback.
- **Attribution:** seed address-tag DB from OFAC SDN + Etherscan/Arkham labels + chainabuse.
- 📌 **Reconcile before demo:** "PT A2Z" (Gary) vs "Oei Hengky Wiryo" (proposal) — same 4,656/22/Rp530B
  figures, two names. Pick one narrative. Also settle naming: **ITTU** vs "FlowTracer"/"TraceChain"/
  "BridgeWatch".

---

## Roadmap: MVP → full ITTU (same architecture)
1. **Hackathon MVP** — the 5 deliverables above, real-arch-lean.
2. **Harden** — add **Neo4j** (persistent cross-case graph + GDS), real RLS multi-agency, chain-of-
   custody end-to-end, address-tag DB at scale.
3. **Go LIVE by toggle** — real blockchain APIs (Bitquery, more chains: ETH/BSC), real fiat feeds
   (bank MoU), live honeypot channels (Telegram/WhatsApp + voice under Polri supervision), real
   multi-agency notification dispatch.
4. **Integrate** — PPATK goAML/IASC reporting, OJK sandbox onboarding, TKDN/local-PT for procurement,
   on-prem (K3s) for data-sovereignty deployments.

---

## Not in Gary's combined scope (noted)
Product Idea 3 (**TravelSync** — VASP Travel Rule / IVMS101 compliance network) is **out** of the
combined 1+2 MVP. Parked as a possible later module — it's compliance-infrastructure, adjacent but
distinct from the forensics core.
