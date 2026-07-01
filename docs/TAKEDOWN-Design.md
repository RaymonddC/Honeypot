# TAKEDOWN — Module Design (deep-dive) · "Investigation Screen"

> Input a TRON wallet → fetch USDT-TRC20 transfers → interactive **Cytoscape.js** transaction graph →
> per-wallet **risk score** (Isolation Forest on 12 features) → flag **5 laundering patterns** → each
> with **confidence + reasoning**. Screen 1 of the MVP, **~60% of build effort**. Grounded in Gary's
> spec + Research-Forensics (Elliptic++, IF-as-triage, TronGrid, NetworkX limits) + ELSA reuse.

---

## Design principles
1. **Isolation Forest is anomaly *triage*, not a fraud classifier.** Pair it with **deterministic
   typology rules** — those carry the court-explainable signal. (Research-Forensics.)
2. **Every score explains itself.** Composite risk = IF score + which patterns fired + which features
   were anomalous, with the exact evidence (txs/nodes). This is the Glass Box / TRM-style contract.
3. **Per-investigation subgraphs are small** (thousands of nodes) → **NetworkX in-memory** is plenty;
   Neo4j deferred. **Lazy multi-hop expansion** — never pull the whole graph upfront.
4. **Cache aggressively** — TRONSCAN/TronGrid free tiers throttle (~5–15 req/s); persist everything
   fetched (Redis + Postgres) so multi-hop tracing doesn't hammer the API.
5. **Validate methodology on Elliptic++, score on our own features** — Elliptic's 166 features are
   anonymized/unreproducible on Indonesian wallets; we compute our own interpretable 12.

---

## Component pipeline

```
 wallet address
      │
      ▼
┌───────────────────┐   TRONSCAN /api/transfer/trc20 (USDT-TRC20 contract) primary
│ Ingestion Adapter │   TronGrid backup · Redis cache · pagination · idempotent upsert
│ (POC fixtures /   │──▶ chain.transactions
│  LIVE api)        │
└─────────┬─────────┘
          ▼
┌───────────────────┐   NetworkX DiGraph; nodes=wallets, edges=transfers(value,ts,hash)
│ Graph Builder     │   lazy BFS expand ≤3 hops on node click
└─────────┬─────────┘
          ▼
┌───────────────────┐   12 features per wallet (see below) → chain.wallet_features
│ Feature Engine    │
└─────────┬─────────┘
          ├───────────────────────────┬───────────────────────────┐
          ▼                           ▼                           ▼
┌───────────────────┐   ┌───────────────────────┐   ┌────────────────────────┐
│ Isolation Forest  │   │ 5 Typology Detectors  │   │ Attribution Overlay    │
│ (sklearn,         │   │ (deterministic, ELSA- │   │ address_tags: exchange/│
│  contamination    │   │  ported): peel chain, │   │ mixer/scam/gambling/   │
│  ≈0.05) → 0..1    │   │ rapid relay, circular,│   │ sanctioned             │
│  anomaly triage   │   │ structuring, fan-out  │   │                        │
└─────────┬─────────┘   └───────────┬───────────┘   └───────────┬────────────┘
          └───────────────┬─────────┴───────────────────────────┘
                          ▼
              ┌────────────────────────────┐   low/med/high + confidence + reasoning
              │ Composite Risk + Reasoning │──▶ chain.wallet_risk_scores
              └─────────────┬──────────────┘
                            ▼
              ┌────────────────────────────┐   Cytoscape elements (nodes risk-colored
              │ Investigation Screen (UI)  │   green→yellow→red, edges sized by amount,
              │ graph · detail card ·      │   arrows=direction) + Glass Box panel +
              │ pattern flags · Glass Box  │   rule-vs-ML side-by-side
              └────────────────────────────┘
```

---

## The 12 features (Gary's canonical set for MVP)
Computed per wallet from its USDT-TRC20 transfer set. These feed the Isolation Forest.

| # | Feature | Signal |
|---|---|---|
| 1 | Transaction frequency / velocity (tx per active day) | automation, burst activity |
| 2 | Volume — total & mean transfer value | throughput |
| 3 | Unique counterparties | fan breadth |
| 4 | Rapid-relay rate (share forwarded quickly) | pass-through/layering |
| 5 | Round-number percentage | structuring signature |
| 6 | Fan-in / fan-out ratio | aggregation vs dispersal |
| 7 | Account age | mule freshness |
| 8 | In/out ratio | pass-through (≈1.0 = layering) |
| 9 | Time-distribution entropy | bursty automation vs organic |
| 10 | Chain depth (multi-hop position) | layering distance |
| 11 | Self-loop count | wash / obfuscation |
| 12 | Max transaction size | outlier value |

> **Reconciliation note:** the data model's initial `chain.wallet_features` columns were a slightly
> different 12. **Gary's 12 above are canonical for the MVP** — `chain.wallet_features` is updated to
> match (see Data-Model reconciliation). `mixer_exposure` and `counterparty_risk` move to the
> **Attribution Overlay** (from `address_tags`), and peel/structuring/cyclic move to the **pattern
> detectors** — so features ≠ patterns, cleanly separated.

---

## The 5 typology patterns (deterministic detectors, explainable)
Each returns a fired-flag + score + **evidence** (the specific txs/nodes) for the reasoning trace.

1. **Peeling chain** — long sequential chain where most value forwards on and a small amount "peels" off each hop.
2. **Rapid relay** — funds forwarded within ~5 minutes, in/out ratio > 0.95 (near-pure pass-through).
3. **Circular transactions** — cycles detected via NetworkX `find_cycle` / `simple_cycles` (wash/mixing).
4. **Structuring / smurfing** — clusters of similar-amount transfers (just under thresholds / round numbers).
5. **Fan-out dispersal** — one input wallet → 10+ output wallets (dispersal across mules).

---

## ML risk scorer
- **`sklearn.ensemble.IsolationForest(contamination≈0.05)`** — unsupervised, O(n), fast; anomaly score
  normalized to 0..1. Fit on the investigation's wallet population (or a reference corpus).
- Positioned as **triage**: surfaces statistical outliers for analyst attention; typology detectors +
  attribution provide the *criminal* signal. A whale/exchange wallet is an outlier but not a criminal.
- **Validation:** benchmark methodology on **Elliptic++** (822k addresses; RF baseline F1≈0.8 reference)
  — for accuracy metrics in the demo, not applied directly to TRON wallets.
- **Rule-vs-ML side-by-side** (Gary's demo ask): show both the IF anomaly view and the deterministic
  pattern view so judges see the complementarity.

## Composite risk + reasoning
- Combine IF anomaly score + fired patterns + attribution exposure → **low / medium / high** with a
  **confidence** and **explicit reasoning** listing anomalous features, fired patterns, and evidence.
- Stored in `chain.wallet_risk_scores` (`iso_forest_score`, `typology_flags` jsonb, `composite_risk`,
  `confidence`, `reasoning`, `model_version`). Drives node color (green→yellow→red) + the Glass Box panel.

---

## Investigation Screen UI (frontend — reuse ELSA design system)
- **Input** wallet address → graph renders (Cytoscape force layout; nodes risk-colored + sized, edges
  amount-sized, arrows = flow direction).
- **Click node** → lazy **BFS expand ≤3 hops**; wallet **detail card** (balance, risk, 12 features,
  tags, reasoning); **path highlight** source→destination.
- **Pattern flags panel** — which of the 5 fired + evidence.
- **Glass Box reasoning panel** — reuse ELSA `ReasoningPanel`; shows the "why" behind each score.
- **Rule-based vs ML toggle** — side-by-side comparison.
- **Export** → feeds **Action Panel** (freeze/LTKM) and **Bridge View** (the crypto side).

---

## Data flow
input wallet → Ingestion Adapter (TRONSCAN, Redis cache) → normalize → `chain.transactions` →
Graph Builder (NetworkX) → Feature Engine (12 features → `chain.wallet_features`) → [Isolation Forest]
+ [5 typology detectors] + [attribution overlay] → Composite Risk + Reasoning → `chain.wallet_risk_scores`
→ Cytoscape elements + colors + Glass Box → UI. Node click → lazy BFS expand (fetch on demand) → recompute.

---

## Performance & drift
- Subgraphs small → NetworkX fine; keep **hop depth ≤3** (Gary) / ≤5–6 max (combinatorial blow-up).
- **Cache** TRONSCAN/TronGrid responses (rate limits); persist to Postgres for cross-investigation reuse.
- **Concept drift** (Elliptic models collapse after regime change) → periodic IF retraining +
  score-distribution monitoring (post-MVP).

## POC ↔ LIVE
| Aspect | POC | LIVE |
|---|---|---|
| Blockchain data | Pre-loaded 15–20 known-suspicious TRON addresses (cached fixtures) — Gary's demo | Live TRONSCAN + TronGrid (Bitquery later) |
| Scoring | Real (deterministic on fixtures) | Real |
| Chains | TRON/USDT-TRC20 | + ETH/BSC later |

## Reuse & build
| Piece | Source | Action |
|---|---|---|
| Blockchain ingestion clients (rate-limit, pagination, normalize) | ELSA (TS) | **Port to Python** + extend for TRON |
| Deterministic anomaly heuristics | ELSA (`executeDetectAnomalies`) | **Port** → the 5 typology detectors |
| Glass Box reasoning panel, WalletDashboardCard, design system | ELSA | **Reuse** in the UI |
| `chain.*` tables | `docs/Data-Model.md` | **Use** (feature columns updated to Gary's 12) |
| Isolation Forest, feature engine, Cytoscape graph, BFS expansion | — | **Build** |

## Open questions
1. **IF fit population** — per-investigation vs. a maintained reference corpus of scored wallets.
2. **Feature normalization** — scaling strategy so IF isn't dominated by volume/max-tx magnitude.
3. **address_tags seeding** — initial tag sources for the attribution overlay (OFAC SDN, Etherscan,
   chainabuse) — coordinate with TRACE.
