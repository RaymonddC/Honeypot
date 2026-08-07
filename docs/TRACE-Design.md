# TRACE — Module Design (deep-dive) · "Bridge View / BridgeWatch"

> Reveals the fiat→crypto **bridge** launderers exploit: correlates suspicious QRIS/bank/mule activity
> (simulated) with real crypto-exchange deposits (real TRON), and visualizes the whole pipeline as a
> **D3.js Sankey**. Screen 2 of the MVP — the visual wow-factor. Focus = the **on-ramp**, the moment
> dirty fiat becomes crypto. Grounded in Gary's BridgeWatch spec + Research-Forensics + Research-RegMarket
> (the BI↔OJK↔PPATK cross-domain gap PPATK Deputy Danang named).

---

## Design principles
1. **The bridge is the point.** Chainalysis/Elliptic trace on-chain; goAML tracks fiat; **nobody
   connects them.** BridgeWatch's whole value is the fiat↔crypto correlation in one view.
2. **Simulated fiat + real crypto.** Real bank/QRIS data isn't public → synthesize the fiat side on the
   **PT A2Z / Oei-Hengky** case params (4,656 accounts · 22 banks · Rp 530B); use **real TRON/USDT** for
   the crypto side. This split is inherent to the POC and honest about it.
3. **Cross-domain by design.** Spans BI (QRIS), OJK (banking + crypto), PPATK (intelligence) — the exact
   coordination gap. Output is a multi-agency alert packet.

---

## Component pipeline

```
┌──────────────────────────┐     ┌───────────────────────────┐
│ Synthetic Fiat Generator │     │ Crypto Deposit Monitor    │
│ PT A2Z pattern:          │     │ TRONSCAN USDT deposits at │
│ QRIS micro-deposits →    │     │ known exchange hot wallets│
│ mule aggregation → bulk  │     │ (address_tags=exchange)   │
│ transfer  (PaySim fallbk)│     │ REAL on-chain data        │
│ → fiat.fiat_transactions │     │ → chain.transactions      │
└────────────┬─────────────┘     └─────────────┬─────────────┘
             │                                 │
             ▼                                 ▼
      ┌─────────────────┐            ┌──────────────────────┐
      │ Mule Network    │            │ Correlation Engine   │
      │ Detection       │            │ amount (fee-tolerant)│
      │ NetworkX community│──────────▶│ + 30-min time window │
      │ detection +DBSCAN│            │ (pandas + scipy)     │
      │ behavioral clusters│          │ → fiat.correlations  │
      └────────┬────────┘            └──────────┬───────────┘
               └──────────────┬─────────────────┘
                              ▼
              ┌────────────────────────────────┐
              │ Sankey Flow Builder (d3-sankey)│  QRIS merchants → mule accounts →
              │ aggregate volumes per stage    │  exchange deposits → USDT wallets → foreign
              └───────────────┬────────────────┘
                              ▼
              ┌────────────────────────────────┐
              │ Bridge View UI (split-screen)  │  left=fiat(sim) · right=crypto(real) ·
              │ fiat | bridge | crypto + alerts│  middle=bridge · confidence-ranked alert feed
              └────────────────────────────────┘
```

### 1. Synthetic Fiat Generator (POC data source; adapter → LIVE bank feed)
- Models the documented PT A2Z laundering pattern: **high-frequency small QRIS deposits** (Rp
  10k–500k) to shell merchants → **rapid aggregation** in mule accounts → **bulk transfer** to crypto-
  exchange bank accounts. Seeded with real case stats (4,656 accounts, 22 banks, Rp 530B).
- Emits `fiat.fiat_accounts` + `fiat.fiat_transactions` (`data_mode=poc`). **PaySim** (6M+ labeled
  mobile-money txs) as a fallback/augmentation.
- **Adapter:** POC = generator; LIVE = real bank/QRIS feed (post-MoU) — same downstream schema.

### 2. Crypto Deposit Monitor (real side — shares TAKEDOWN ingestion)
- Tracks **USDT-TRC20 deposits at known exchange hot-wallet addresses** (from `chain.address_tags`
  where `category='exchange'`) via TRONSCAN. Real on-chain data → `chain.transactions`.

### 3. Correlation Engine (the bridge)
- Matches fiat-side behavioral signatures (deposit timing, aggregated amounts, account velocity)
  against crypto-side deposit patterns: **amount match within fee tolerance** (IDR→USDT via a rate
  source) **AND timing within a 30-minute window**. Implemented in **pure Python** (`app/trace/correlation.py`)
  — no pandas/scipy — for time-series correlation + fuzzy amount matching.
- Emits `fiat.correlations` (`fiat_tx_id`, `crypto_tx_id`, `time_delta_seconds`, `amount_match`,
  `confidence`). Each becomes a `[:CORRELATED]` edge in the graph model.

### 4. Mule Network Detection
- **NetworkX community detection** (Louvain) on the synthetic fiat transaction graph to surface mule
  clusters; **DBSCAN** (scikit-learn) behavioral clustering on account features (many-in / brief-hold /
  few-out fingerprint). Flags accounts matching the gambling-intermediary pattern.

### 5. Sankey Flow Builder (D3 `d3-sankey`)
- Aggregate fund flows across stages: **QRIS merchants → mule bank accounts → exchange deposits → USDT
  wallets → foreign destinations**, quantifying volume at each stage. The "Rp-hundreds-of-billions
  flowing through the pipeline" visual.

### 6. Bridge View UI (frontend — reuse ELSA design system)
- **Split-screen:** left = fiat (QRIS/bank flows, simulated) · right = crypto (TRON/USDT, real) · middle
  = highlighted **bridge** connections. **Sankey** on top; **confidence-ranked alert feed** of suspected
  on-ramp events; **drill into** a mule cluster. **Export** → Action Panel (multi-agency alert packet
  for the bridge nodes).

---

## Data flow
Synthetic Fiat Generator → `fiat.*` (POC) ‖ Crypto Deposit Monitor (TRONSCAN, real) → `chain.transactions`
→ Mule Detection (Louvain + DBSCAN) + Correlation Engine (amount + 30-min) → `fiat.correlations` →
Sankey Builder (aggregate) → Bridge View UI (split-screen + Sankey + alerts) → Action Panel.

---

## POC ↔ LIVE
| Aspect | POC | LIVE |
|---|---|---|
| Fiat side | Synthetic generator (PT A2Z params) / PaySim | Real bank + QRIS feed (post-MoU) |
| Crypto side | Real TRON (or cached fixtures for offline demo) | Real TRON + more chains |
| Correlation | Real engine on the above | Real engine |
| Alerts | Mock packet to bank/exchange/PPATK | Real multi-agency dispatch (via UNCOVER) |

*(Fiat stays simulated even in early LIVE until bank MoUs land — the adapter makes that swap seamless.)*

---

## Reuse & build
| Piece | Source | Action |
|---|---|---|
| Design system, split-screen shell | ELSA | **Reuse** |
| Blockchain ingestion (crypto side) | ELSA (port) / shared with TAKEDOWN | **Reuse** |
| `fiat.*`, `chain.transactions`, `address_tags` | `docs/Data-Model.md` | **Use** |
| Synthetic fiat generator (PT A2Z), correlation engine, mule clustering, d3-sankey | — | **Build** |

## Open questions
1. **Exchange hot-wallet list** — seed `address_tags(category='exchange')` from public sources
   (Arkham/Etherscan/community) for the crypto-deposit monitor.
2. **IDR→USDT rate source** — price API + historical rates for amount matching.
3. **Fee-tolerance + time-window calibration** — tune against the synthetic ground truth before demo.
4. **Narrative name** — reconcile PT A2Z vs Oei Hengky Wiryo (same case) for the Sankey story.
