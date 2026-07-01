# ITTU — Development Plan & Research Briefing

> **ITTU** (Infiltrate, Trace, Takedown & Uncover) — AI-powered financial-crime forensics
> platform for Indonesia's digital finance ecosystem.
> Status: **greenfield / planning**. Source: `PIDI Subs 2.pdf` (23-page proposal).
> This doc consolidates 4 parallel research streams (Honeypot, Forensics, Stack, Reg/Market)
> and proposes the build. **No code written yet — this is plan-only.**

---

## 0. Guiding principles (from the user)

1. **No timeline-driven compromises.** The proposal's 3-month MVP is *not* a constraint — we
   leverage AI to build well. Decisions are made on engineering merit and product quality.
2. **POC ↔ LIVE by a toggle.** Every external dependency sits behind an adapter interface with a
   `MODE = POC | LIVE` switch (per-module). Same UI, same code paths, swapped data sources.
   Regulators get a safe, demo-able POC that flips to production without a rewrite.
3. **Evidence-grade by design.** This is a forensics tool feeding lawful enforcement — chain of
   custody, confidence scores + explicit reasoning, and audit trails are first-class, not add-ons.

---

## 1. Does the proposal hold up? (Reg/Market verification)

**Core thesis is sound and well-evidenced:** goAML genuinely has *no* on-chain capability; recovery
is stuck at **4.76%**; losses are large and rising; UU ITE Pasal 5 gives a solid legal basis for
electronic evidence. The pain is real.

**Fix these before the proposal circulates further (for Gary):**

| Claim in proposal | Reality | Action |
|---|---|---|
| "18 licensed crypto exchanges" | **25 licensed traders / 29 ecosystem entities** (OJK whitelist Dec 2025; supervision moved Bappebti→OJK Jan 2025) | Correct the number |
| "QRIS = Rp 286.84T deposit channel" | Rp 286.84T is **total online-gambling turnover 2025**; deposits were Rp 36.01T; QRIS is a rising *subset* | Reword |
| "FATF grey-list risk" | **Wrong** — Indonesia is a full FATF member (2023, passing eval), on regular follow-up | Drop/soften; reframe around 2023 MER VASP-supervision gaps + May 2025 follow-up |
| "No foreign forensic tools here" | **Chainalysis already courts Indonesian regulators** | Reposition edge on **sovereignty + locality + price + Bahasa/Rupiah workflows + TKDN**, not incumbent absence |
| POJK 27/2024 = "the AML rule for crypto" | It's market-conduct; AML/CFT obligations live in POJK 8/2023 + SEOJK 16/2025 | Tighten framing |
| "Rp 750M/yr foreign tools" | Plausible as **entry/single-seat** price; enterprise runs far higher | Present as "entry-level seat pricing" |

**GTM insight:** the **OJK Regulatory Sandbox** is the realistic entry wedge (active, busy), paired
with an **IASC-member bank pilot**, then **LKPP e-Katalog with TKDN certification via a local PT**.
**PDP Law (UU 27/2022) + PP 71/2019 likely mandate on-prem/local hosting** for PPATK/OJK/Polri —
this reinforces the container-portable architecture below.

---

## 2. Tech stack — proposal vs. recommendation

| Area | Proposal | **Recommendation** | Change |
|---|---|---|---|
| Backend framework | Python | **FastAPI** (Pydantic v2, SQLAlchemy 2.0 async + asyncpg, Alembic) | ✅ Confirm |
| Architecture | 4-layer **microservices** | **Modular monolith** — the 4 layers become strong internal modules; extract only workers/honeypot as separate processes when justified | ⚠️ **Deviate** |
| Frontend | Next.js **14** + TS | **Next.js 16 LTS** + TS, App Router, Turbopack, **shadcn/ui + Tailwind** | ⚠️ **Deviate** |
| Primary DB | PostgreSQL | **PostgreSQL** — single source of truth; **JSONB** for transcripts/metadata; **Row-Level Security day one** | ✅ Confirm + harden |
| Graph store | (Postgres) | **NetworkX in-memory** for per-case subgraphs → **Neo4j** for persistent cross-case graph + interactive UI | ➕ Two-tier |
| Cache / broker | — | **Redis** (blockchain cache + queue broker + rate-limit + session) | ➕ Add now |
| Async tasks | — | **Dramatiq + Redis** (honeypot turns, blockchain polling, ML scoring); APScheduler for polling; FastAPI BackgroundTasks only for sub-second work | ➕ Add |
| LLM orchestration | "LLM agents" | **Direct Anthropic SDK + thin custom agent loop** (no LangChain); `pydantic-ai` optional for typed output | ➕ Specify |
| Auth | JWT + RBAC | **JWT (claims: agency_id, role) + RBAC + Postgres RLS backstop** | ✅ Confirm + harden |
| PDF | ReportLab | **ReportLab** — run in the task queue (blocking) | ✅ Confirm |
| Deploy (dev/pilot) | Docker, AWS/GCP | **Docker Compose** (dev) → **ECS+Fargate / GKE** (cloud pilot) → **K3s/MicroK8s** (on-prem, portable OCI images) | ➕ Specify |

**Non-negotiables that emerged:** (a) modular monolith over microservices; (b) Postgres RLS from day
one — one missed `WHERE` = cross-agency leak, catastrophic for this domain; (c) keep everything
container-portable so on-prem/data-sovereignty is a config choice, not a re-architecture.

---

## 3. Architecture — the POC/LIVE toggle

Every external boundary is an **adapter interface** with two implementations, selected by config:

| Boundary | `POC` adapter | `LIVE` adapter |
|---|---|---|
| Blockchain data (TRACE) | cached/sample wallet & tx fixtures | TronGrid (raw USDT-TRC20) + Bitquery GraphQL (enrichment) + Etherscan v2 (ETH/BSC) |
| Fiat data (TRACE) | PaySim / synthetic Oei-Hengky-style dataset | real bank feed (post-MoU) |
| Honeypot (INFILTRATE) | scripted/replayed scam transcripts | live LLM agent on channels, human-in-the-loop, under Polri supervision |
| Notifications (UNCOVER) | mock/no-op sink (logged) | real multi-agency dispatch |
| LLM provider | can stub deterministic responses | Anthropic / OpenAI live |

Config: a single `MODE` env var with **per-module overrides** (e.g. run TAKEDOWN LIVE on real chain
data while INFILTRATE stays POC). Adapters share identical interfaces + response schemas so nothing
downstream knows or cares which mode is active.

**Module map (inside the modular monolith):**
```
app/
  core/        config, MODE/adapter registry, auth (JWT+RLS), audit, chain-of-custody
  infiltrate/  honeypot agent, persona/state, entity extraction, classifier, clustering
  trace/       blockchain adapters, fiat adapters, correlation engine (BridgeWatch)
  takedown/    feature engine (12 indicators), Isolation Forest + typology rules, graph analysis
  uncover/     ReportLab doc gen, notification hub, Action Panel
  intel/       intelligence DB models (accounts, wallets, syndicates, sessions), address-tag DB
workers/       Dramatiq actors (honeypot turns, polling, scoring, reporting)
frontend/      Next.js 16 investigator dashboard (Cytoscape.js, d3-sankey, shadcn/ui)
```

---

## 4. Module technical direction (from research)

### INFILTRATE (Honeypot)
- **Proven field.** Benchmark against *"Send to which account?"* (arXiv 2509.08493): target **~32%
  info-disclosure rate, ~70% human-acceptance**; the real bottleneck is **engagement takeoff (<49%
  reply)** → architect for high conversation volume.
- **Stay strictly reactive & victim-framed** — never initiate/solicit fraud, never access scammer
  systems, never redistribute seized data. Keeps clear of entrapment doctrine + UU ITE Arts. 30/32/33/36.
- **Persona = structured profile** (not a paragraph) + **human-realism layer outside the LLM**
  (randomized delays, typos, Bahasa + regional code-switching) — the #1 anti-detection lever.
- **Per-conversation state store** with an extraction checklist; goal-directed dialogue toward the
  "which account?" moment. **Human-in-the-loop** at high-value turns (money question, bot-probing).
- **Hybrid entity extraction, always validated:** regex+checksums (wallets/phones/URLs, prioritize
  **TRON/USDT-TRC20**) → LLM/JSON for obfuscated/contextual entities + relationships → fine-tuned
  **IndoBERT** (IPerFEX / BiLSTM-CRF) for person/org/alias feeding syndicate clustering. Indonesian
  bank accounts have no checksum → need **bank-name context anchors** (BCA, Mandiri, BRI, BNI…).
- **Chain of custody day one:** append-only hashed raw logs, per-entity provenance
  (message→method→confidence→review), preserved originals, documented model/prompt versions.
- **Secure the dual-use engine** (it's functionally a scam bot); **confidence-score + corroborate**
  every entity to defeat scammer data-poisoning.

### TAKEDOWN (Analytics)
- **Isolation Forest = anomaly *triage*, not a fraud classifier.** Pair with **deterministic typology
  rules** (mixing, peel chains, structuring, cyclic flows) for court explainability. Add
  semi-supervised/PU learning if any scam wallets get labeled.
- **12 indicators** (5 discriminative): tx velocity · total/mean volume · unique counterparties ·
  in/out balance ratio · **peel-chain signature** · **mixer exposure** · lifetime/dormancy · temporal
  burstiness · **round-number/structuring ratio** · rapid turnover · **cyclic involvement** ·
  **counterparty-risk exposure**.
- **Validate methodology on Elliptic++** (822k addresses × 56 features — the wallet-level variant),
  but compute **our own interpretable features** from raw chain data (Elliptic's 166 features are
  anonymized/secret and can't be reproduced on Indonesian wallets). RF baseline F1 ≈ 0.8.
- **Two-tier graph:** NetworkX for per-case subgraphs (small — fine) + **Neo4j** for persistent
  cross-case graph and interactive queries. Louvain (rings) + `simple_cycles` (layering) +
  betweenness (hubs). Keep hop depth ≤ 5–6.
- **Attach confidence + explicit reasoning to every risk flag** (TRM Labs playbook) — matters more
  than raw accuracy for an evidentiary tool.
- **Plan for concept drift** (Elliptic models collapse after a regime change) → periodic retraining +
  score-distribution monitoring.

### TRACE (Data aggregation + BridgeWatch)
- **API stack:** **TronGrid** (raw USDT-TRC20) + **Bitquery GraphQL** (enrichment/correlation) +
  **Etherscan v2** unified key (ETH/BSC). Free ceilings are ~5 req/s → **rate-limit-aware caching
  queue**, persist everything fetched. Abstract behind an adapter (Etherscan is cutting free access).
- **Correlation engine:** match fiat transfers ↔ crypto deposits by time-window + amount → end-to-end
  flow. **d3-sankey** for the fiat→crypto flow diagram.
- **Biggest realistic gap vs pros = attribution data.** Seed an **address-tagging DB** from OFAC SDN,
  Etherscan/Arkham labels, chainabuse, community lists. Note account-based (Tron/ETH) clustering is
  harder than Bitcoin UTXO — lean on behavioral/temporal correlation.

### UNCOVER (Action)
- **ReportLab** blocking-doc + STR generation in **PPATK/IASC-compatible formats** (run in task
  queue). **Notification Hub** (POC mock → LIVE multi-agency dispatch). Action Panel = one-click
  analysis→action, output in formats investigators already use.

### Frontend
- **Next.js 16 + shadcn/ui + Tailwind.** **Cytoscape.js** primary investigator graph (case-sized,
  built-in algorithms), **d3-sankey** for fund flows, **Sigma.js/WebGL** in reserve above ~5k nodes.
  Multi-agency login (RBAC), audit-trail views, role-scoped data (backed by RLS).

---

## 5. Build plan (dependency-ordered, not time-boxed)

- **Phase 0 — Foundations.** Repo scaffold (FastAPI modular monolith + Next.js 16), Docker Compose
  (Postgres, Redis, Neo4j), **adapter/MODE framework**, **JWT + RBAC + RLS** skeleton, base schema +
  Alembic, Dramatiq wiring, CI, audit + chain-of-custody primitives. *Unblocks everyone.*
- **Phase 1 — TRACE data layer.** Blockchain adapters (POC fixtures + LIVE TronGrid/Bitquery/Etherscan),
  rate-limit-aware caching queue, fiat adapters (PaySim/synthetic + LIVE stub), address-tag DB seed.
- **Phase 2 — TAKEDOWN.** 12-feature engine, Isolation Forest + typology rules, NetworkX case-graph
  analysis (cycles/community/hubs), confidence+reasoning scoring; validate on Elliptic++.
- **Phase 3 — INFILTRATE.** Honeypot agent (Anthropic SDK + thin loop), persona/state, human-realism
  layer, hybrid entity extraction, classifier, syndicate clustering, chain-of-custody logging.
  POC replay ↔ LIVE deployment (gated, human-in-loop).
- **Phase 4 — TRACE correlation + BridgeWatch.** Fiat↔crypto correlation engine, end-to-end flow
  assembly, Sankey data.
- **Phase 5 — UNCOVER.** ReportLab docs (PPATK format), notification hub, Action Panel.
- **Phase 6 — Frontend investigator dashboard.** Login/RBAC, Graph Explorer (Cytoscape), Sankey,
  Action Panel UI, audit views.
- **Cross-cutting throughout:** security (RLS, custody, audit), explainability (confidence+reasoning
  everywhere), observability, POC demo scenarios (Oei-Hengky-based onboarding sim).

Phases 2 and 3 can run largely in parallel once Phase 1's data contracts exist.

---

## 6. Agent team for the build (orchestrated by Lead, agents message each other)

| Agent | Maps to | Owns |
|---|---|---|
| **Lead** (main session) | Project Lead / you+Gary | Orchestration, API-contract arbitration, integration, keeping you in the loop |
| **Backend-Core** | Raymond (backend) | Scaffold, auth/RLS, adapter+MODE framework, TRACE, UNCOVER, Dramatiq workers |
| **AI-Engineer** | Raymond (AI) | INFILTRATE (honeypot + entity extraction) and TAKEDOWN (ML + graph) |
| **Frontend** | Wilbert | Next.js 16 dashboard, Cytoscape graph, d3-sankey, Action Panel UI |
| **QA/Security** (optional) | — | RLS isolation tests, chain-of-custody verification, adversarial checks |

**Coordination:** Backend-Core publishes the OpenAPI contract + shared schemas; Frontend and
AI-Engineer consume them; the Lead resolves cross-cutting decisions. Agents talk directly (e.g.
Frontend ↔ Backend-Core on endpoint shapes, AI-Engineer → Frontend on the risk-score/graph schema).

---

## 7. Decisions — LOCKED (2026-07-01)

1. **Stack deviations — APPROVED (all).** Modular monolith, Next.js 16, Redis + Dramatiq, Postgres
   RLS day one. Keep FastAPI / PostgreSQL / JWT-RBAC / ReportLab / Docker / Cytoscape + D3.
   **LLM access via a self-hosted LiteLLM gateway** (swappable Anthropic/Gemini/OpenRouter/Jatevo) with
   tiered cost routing — NOT a single hardcoded SDK. Thin custom agent loop, no LangChain. (See §9.3.)
2. **Graph store — Neo4j DEFERRED (updated 2026-07-01).** Reconciling Gary's MVP scope: use
   **NetworkX in-memory only** for the hackathon MVP (Neo4j is a rebuildable projection in our data
   model, so deferring costs nothing). **Add Neo4j post-hackathon** when the persistent cross-case
   graph goes interactive/large. *(Reverses the earlier "Neo4j from start" pick.)*
3. **Agent team — 4 agents + Lead.** Backend-Core, AI-Engineer, Frontend, **QA/Security** (RLS
   isolation tests, chain-of-custody verification, adversarial checks). Lead = main session.
4. **Timeline — hackathon first, then full product.** Ship the MVP for the hackathon, then continue
   into full ITTU on the same architecture. See `docs/MVP-Scope.md`.
5. **MVP scope — Gary's 4 screens + honeypot.** Investigation (TAKEDOWN) · Bridge View (TRACE/
   BridgeWatch) · Action Panel (UNCOVER) · Response Dashboard · INFILTRATE honeypot (text+voice, POC
   mode for demo). Product Idea 3 (TravelSync) is out of scope.
6. **Build strategy — "real architecture, run lean."** Build the MVP on the locked stack (Postgres+RLS,
   Next 16, FastAPI modular monolith, adapter/MODE toggle, LiteLLM) minus Neo4j — so the POC flips to
   LIVE without a rewrite. NOT Gary's throwaway SQLite/NetworkX-only/Next-14 hackathon stack.
7. **Next step — refine the plan further (still plan-only).** No build yet; deepen per-module design
   docs before writing code.

## 9. Reuse map — existing projects (surveyed 2026-07-01)

Three sibling projects were surveyed for reuse. **None is a drop-in ITTU**, but two supply valuable
parts. The catch: the reusable code spans **three different stacks**, so this is a *consolidation*
onto our locked stack, not a fork.

| Project | What it really is | Stack | Verdict |
|---|---|---|---|
| **ITTUV2** | Unrelated Chrome extension (Gemini Nano mindmaps) — name is a red herring | vanilla JS extension | **Ignore** |
| **OLAF** | Elderly-care AI voice companion | Python/FastAPI + **Google ADK + Gemini + Firebase** + Next.js 15 | **Reuse patterns** (INFILTRATE template) |
| **ELSA** | Chat-based AI wallet analyzer (NOT a graph explorer — no Cytoscape/Neo4j/ML) | **Node/Express + OpenAI + Elasticsearch** + React 19/Vite + Tailwind v4 + shadcn/Radix | **Reuse UI + ingestion + audit pattern** |

### What we take from each
**From OLAF (→ INFILTRATE):** agent+tools+persona-string scaffolding; the **covert side-effect tool
pattern** (`flag_emotional_distress` → honeypot `record_entity`/`escalate`); structured-JSON
extraction; FastAPI skeleton, config, docker-compose, CI; **and — now that voice is a first-class
channel — its voice bidi-streaming pipeline** (STT→LLM→TTS turn management, duplicate-suppression,
defensive stream close) powers INFILTRATE's voice call-baiting (§ INFILTRATE-Design 1a). *Drop*
Firebase and Google ADK — re-implement patterns on our Anthropic-via-LiteLLM + Postgres stack; keep
STT/TTS modular/provider-swappable (Indonesian-capable).

**From ELSA (→ frontend + TRACE/TAKEDOWN):**
- 🎨 **The design system the user loves** — emerald-on-black dark theme (`index.css`), Tailwind v4 +
  shadcn/Radix `ui/` primitives, `WalletDashboardCard`, chat/sidebar shell. Highest-ROI reuse.
- 🔍 **"Glass Box" reasoning-trace UI** (`ReasoningPanel.tsx`) — renders each tool call, its args, the
  raw query, and timing. This *is* the court-grade explainability the forensics research demanded
  (TRM-Labs "confidence + reasoning per flag"). Reuse across the whole app as the audit/explainability UI.
- ⛓️ **Blockchain ingestion clients** — BTC (blockchain.info) + ETH (Etherscan v2): rate-limiting,
  Zod schemas, pagination, normalization. Port to Python and extend with TronGrid + Bitquery.
- 🚩 **Deterministic anomaly heuristics** (`executeDetectAnomalies`) — large-tx, rapid-sequence,
  round-number, dormant-reactivation, fan-in/out. These become TAKEDOWN's **typology-rule layer**
  (the explainable complement to Isolation Forest). Port to Python.

**ELSA is NOT reusable for:** graph engine, graph viz, Isolation Forest, Neo4j/NetworkX,
multi-hop tracing, address clustering — all absent. Those are **build-new** regardless.

### Stack tensions this creates (decisions needed — see §10)
1. **Frontend:** ELSA's loved UI is **React 19 + Vite (SPA)**, but we locked **Next.js 16**. shadcn/
   Radix/Tailwind port cleanly to Next.js, so we *can* preserve the look — but porting has some cost
   and risk of losing exact feel. Alternative: keep ELSA's Vite-React shell (an SPA behind auth is
   fine for an internal investigator tool). **Recommendation: Next.js 16 + port ELSA's design system.**
2. **Blockchain clients:** ELSA's are TypeScript. **Recommendation: port to Python** (single-language
   backend) using ELSA as the reference spec; extend with TronGrid + Bitquery.
3. **LLM provider — RESOLVED via a gateway.** Instead of hardcoding one SDK, route every LLM call
   through a **provider-agnostic gateway** so providers are swappable by config and cheap models are
   used where they suffice. **Decision:**
   - **LiteLLM (self-hosted) as the core gateway** — OpenAI-compatible, fronts Anthropic + Gemini +
     OpenRouter + **Jatevo** + local/fine-tuned models; lowest-cost/latency/rate-limit-aware/custom
     routing + fallback; **data stays on our network** (satisfies PDP/on-prem). Runs on the Postgres +
     Redis + Docker we already have.
   - **Tiered model routing:** cheap/free tier (Gemini Flash / Jatevo open models e.g. Qwen) for
     rapport/filler turns (the high-volume bulk); strong tier (**Claude**) for disclosure-critical
     turns + structured entity extraction. This is both a cost win and a quality win, and matches the
     "architect for volume" honeypot finding.
   - **Jatevo** = Indonesian/SEA OpenAI-compatible inference (Asia-hosted, cheap open models) → the
     preferred cheap + **in-region data-locality** upstream for LIVE. **OpenRouter** = convenient POC
     upstream. ("9Router" unverified — likely a misremembered name; not used.)
   - **POC ↔ LIVE:** POC → OpenRouter / Gemini free tier; LIVE → self-hosted LiteLLM + Jatevo for
     sovereignty. The gateway is itself a POC/LIVE adapter boundary.
4. **Transaction store:** ELSA uses Elasticsearch; we locked Postgres. **Recommendation: Postgres as
   source of truth** (indexed); revisit ES only if tx-search perf demands — don't add a datastore yet.
5. **Auth:** reuse ELSA's Google-OAuth→JWT *login* UX, but issue our own JWT (agency_id/role claims)
   backed by **Postgres RLS** (not Firebase Auth). Keeps the locked security model.

### Net effect on effort
- **INFILTRATE** (priority): patterns from OLAF, but the defining pieces (channels, scam NER,
  clustering, custody) are net-new. See `docs/INFILTRATE-Design.md`.
- **Frontend:** big head start from ELSA's design system + Glass Box; net-new = graph viz, Sankey,
  Action Panel, multi-agency dashboards.
- **TRACE:** ingestion clients ported from ELSA + extended (Tron/Bitquery) + net-new correlation engine.
- **TAKEDOWN:** ELSA anomaly heuristics → typology-rule layer; net-new = Isolation Forest, NetworkX,
  Neo4j, graph viz.
- **UNCOVER:** net-new.

---

## 8. Refinement backlog (current focus — plan-only)

Deeper design docs, one per area:
- ✅ **INFILTRATE design** — `docs/INFILTRATE-Design.md` (agent loop, persona, extraction, custody,
  **text + voice channels**). DONE.
- ✅ **Data model & schema** — `docs/Data-Model.md` (Postgres schemas + RLS + Neo4j graph model +
  custody + POC/LIVE isolation, all 4 modules). DONE.
- ✅ **UNCOVER design** — `docs/UNCOVER-Design.md` (Action Panel: freeze PDF + goAML LTKM draft +
  multi-agency alert, evidence hashing, POC/LIVE dispatch). DONE.
- ✅ **TAKEDOWN design** — `docs/TAKEDOWN-Design.md` (TRONSCAN ingestion, Gary's 12 features, Isolation
  Forest + 5 typology patterns, NetworkX graph + BFS, Cytoscape UI, confidence+reasoning). DONE.
  *(Data-Model `wallet_features` reconciled to Gary's canonical 12.)*
- ✅ **TRACE design** — `docs/TRACE-Design.md` (Bridge View: synthetic fiat generator, crypto deposit
  monitor, correlation engine, mule clustering, d3-sankey, split-screen UI). DONE.
- ✅ **Adapter & MODE framework spec** — `docs/Adapter-MODE-Framework.md` (interfaces for every POC/LIVE
  boundary, config shape, registry/factory, data_mode enforcement). DONE.
- ✅ **API contract** — `docs/API-Contract.md` (HTTP/WS surface, auth, per-module endpoints). DONE.
- ✅ **Response Dashboard spec** — `docs/Response-Dashboard.md` (metrics + data sources). DONE.
- ✅ **Security/evidence spec** — `docs/Security-Evidence.md` (RLS, custody, explainability, legal). DONE.

**All design docs complete.** Master index: `docs/README.md`. Ready for build Phase 0 when you are.
