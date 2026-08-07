# ITTU — Plan & Design Index

**ITTU** (Infiltrate, Trace, Takedown & Uncover) — AI-powered financial-crime forensics platform for
Indonesia. This folder is the complete planning + design set. **Build status (on `main`):** P0–P5 all
shipped — Investigation, Bridge, Action Panel, Response Dashboard, the **P4/P4b honeypot** (text +
live-mic voice), and **P5 auth/RLS** (JWT + RBAC + row-level isolation, `test_rls_isolation.py`).
Investigation runs as an **async job** (202 + poll). **270 backend tests green.** Case-centric hub
screens (`/home`, `/case`, `/guide`) now front the four pillars. Source: `../PIDI Subs 2.pdf`.

---

## 📄 Documents

| Doc | What it covers |
|---|---|
| **[ITTU-Development-Plan.md](ITTU-Development-Plan.md)** | Master plan — research briefing, reuse map, locked decisions, backlog. Start here. |
| **[MVP-Scope.md](MVP-Scope.md)** | Hackathon MVP: Gary's 4 screens + honeypot; "real architecture, run lean"; roadmap. |
| **[Data-Model.md](Data-Model.md)** | Postgres schema + RLS + Neo4j graph model + custody + POC/LIVE isolation. |
| **[Adapter-MODE-Framework.md](Adapter-MODE-Framework.md)** | The POC↔LIVE toggle backbone — interfaces, config, registry. |
| **[INFILTRATE-Design.md](INFILTRATE-Design.md)** | Honeypot (text + voice): agent loop, extraction, syndicate clustering, custody. |
| **[TAKEDOWN-Design.md](TAKEDOWN-Design.md)** | Investigation Screen — 12 features, Isolation Forest + 5 patterns, graph. |
| **[TRACE-Design.md](TRACE-Design.md)** | Bridge View — synthetic fiat + real crypto, correlation, Sankey. |
| **[UNCOVER-Design.md](UNCOVER-Design.md)** | Action Panel — freeze PDF + goAML LTKM + multi-agency alert. |
| **[Response-Dashboard.md](Response-Dashboard.md)** | Metrics screen — time-to-freeze, recovery rate. |
| **[API-Contract.md](API-Contract.md)** | HTTP/WS surface for parallel build. |
| **[Security-Evidence.md](Security-Evidence.md)** | RLS, chain-of-custody, explainability, legal anchors. |
| **[Identity-Access-Architecture.md](Identity-Access-Architecture.md)** | Target IdP/RBAC/RLS model — Keycloak broker, delegated admin, role-mapping, cross-agency sharing. |
| **[Frontend-Design.md](Frontend-Design.md)** | Design system (ELSA tokens) + screen designs + [live mockup](https://claude.ai/code/artifact/d592d92c-de21-45f8-b609-ab88e7fd8661). |

---

## 🎬 The demo narrative (one thread through all 5 deliverables)
Honeypot extracts a scammer's TRON wallet + mule account → **Investigation** scores & graphs the
wallet, flags a peeling chain → traces to an exchange deposit → **Bridge View** shows the
QRIS→mule→crypto Sankey with the timing-correlated bridge → **Action Panel** fires the freeze request +
goAML LTKM + multi-agency alert → **Response Dashboard** shows time-to-freeze collapsing to minutes.

---

## 🔒 Locked decisions (2026-07-01)
- **Timeline:** hackathon MVP first → then full ITTU on the same architecture.
- **Scope:** Gary's 4 screens (Investigation/TAKEDOWN, Bridge/TRACE, Action Panel/UNCOVER, Response
  Dashboard) **+ INFILTRATE honeypot** (text+voice, POC mode for demo). TravelSync out of scope.
- **Strategy:** "real architecture, run lean."
- **Stack:** FastAPI modular monolith · Postgres + **RLS day one** · **Next.js 16** + shadcn (port
  ELSA design) · Dramatiq + Redis · **LiteLLM gateway** (Anthropic/Gemini/OpenRouter/**Jatevo**,
  tiered routing) · ReportLab · Cytoscape.js · d3-sankey. **Neo4j deferred** (NetworkX-only for MVP).
- **Reuse:** OLAF → honeypot patterns + voice pipeline · ELSA → UI/design system + Glass Box +
  ingestion clients + anomaly rules. (ITTUV2 = unrelated, ignore.)
- **Every boundary** behind an adapter with `MODE=poc|live`.

## 👥 Build team (4 agents + Lead)
Lead (orchestration) · **Backend-Core** (scaffold, auth/RLS, adapters, TRACE, UNCOVER, workers) ·
**AI-Engineer** (INFILTRATE, TAKEDOWN) · **Frontend** (Next.js 16, Cytoscape, Sankey, Action Panel) ·
**QA/Security** (RLS tests, custody verification, adversarial). Agents message each other on contracts.

---

## ✅ Build-readiness checklist (before Phase 0)
- [ ] Reconcile narrative: **PT A2Z vs Oei Hengky Wiryo** (same case) — pick one.
- [ ] Settle product **name**: ITTU vs FlowTracer/TraceChain/BridgeWatch.
- [ ] Get **API keys**: TRONSCAN/TronGrid, LLM providers (Anthropic/Gemini/Jatevo), STT/TTS.
- [ ] Obtain **goAML XML schema** version (for LTKM draft shape).
- [ ] Seed **address-tag** sources (OFAC SDN, Etherscan/Arkham, chainabuse).
- [ ] Confirm proposal fixes with Gary (18→25 exchanges, QRIS number, FATF framing).
- [ ] Stand up **LiteLLM** gateway config (tiered routing).

## 🚧 Phase 0 (when build starts)
Repo scaffold (FastAPI modular monolith + Next.js 16) · Docker Compose (Postgres, Redis) · adapter/
MODE framework skeleton + registry · JWT + RBAC + **RLS** + base schema/Alembic · Dramatiq wiring ·
LiteLLM gateway · custody/audit primitives · CI. *Unblocks all four module agents.*
