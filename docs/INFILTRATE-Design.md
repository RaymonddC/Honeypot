# INFILTRATE — Module Design (deep-dive)

> The AI Honeypot. An LLM poses as a scam victim on **chat channels AND voice calls**, engages fraudsters,
> extracts entities (accounts/wallets/phones/URLs), classifies the crime, clusters syndicates, and
> feeds the Intelligence DB — **evidence-grade, strictly reactive/victim-framed, human-in-the-loop.**
> Priority module. Grounded in Research-Honeypot (arXiv 2509.08493, Apate, IPerFEX) + OLAF reuse.

---

## Design principles (hard constraints)

1. **Strictly reactive & victim-framed.** The agent NEVER initiates/solicits fraud, NEVER accesses
   scammer systems, NEVER redistributes seized data. It only converses and records what scammers
   *voluntarily send*. This keeps us clear of entrapment doctrine + UU ITE Arts. 30/32/33/36. Enforced
   in the system prompt **and** by tool-gating (no tool can send money/PII or access external systems).
2. **Evidence-grade from message #1.** Append-only, SHA-256-hashed, timestamped raw logs; per-entity
   provenance (message → method → confidence → analyst review); documented model/prompt versions.
   Meets UU ITE Pasal 5 electronic-evidence standard; survives court challenge.
3. **Never trust a raw LLM entity.** Every extracted entity is cross-validated through deterministic
   validators, confidence-scored, and corroborated before it's "actionable" (defeats scammer
   data-poisoning, prevents hallucinated evidence).
4. **Human-in-the-loop at high-value turns.** Money question, bot-probing, or imminent disclosure →
   escalate to an analyst. Raises acceptance rate, cuts legal/ethical risk.
5. **Architect for volume.** Engagement takeoff is <49% and info-disclosure ~32% — signal requires
   many concurrent sessions. Persona pool + Dramatiq-backed concurrent conversations.
6. **Secure the dual-use engine.** This is functionally a working scam bot — access control, audit,
   abuse monitoring, and a kill switch are mandatory.

---

## Component architecture

```
                 ┌──────────────────────────────────────────────────────────┐
  scammer  ⇆     │  Channel Adapter — TEXT (TG/WA/forums) + VOICE (STT/TTS) │
  (chat/call)    │  POC: replay transcripts & call audio | LIVE: real chans │
                 └───────────────┬──────────────────────────┬───────────────┘
                                 │ inbound msg               │ outbound reply
                    ┌────────────▼───────────┐   ┌───────────▼────────────┐
                    │  Custody Log (hash+ts, │   │  Human-Realism Layer   │
                    │  append-only)          │   │  (delays, typos,       │
                    └────────────┬───────────┘   │  Bahasa code-switch)   │
                                 │               └───────────▲────────────┘
                    ┌────────────▼───────────────────────────┴────────────┐
                    │  Conversation Orchestrator (Anthropic SDK, thin loop)│
                    │  persona + state + extraction checklist + summary    │
                    │  tools: record_entity / flag_scam_signal /           │
                    │         update_syndicate_link / escalate_to_analyst  │
                    └────┬──────────────────────┬─────────────────┬────────┘
                         │                      │                 │
             ┌───────────▼─────────┐  ┌─────────▼────────┐  ┌─────▼──────────┐
             │ Entity Extraction   │  │ Crime Classifier │  │ Human-in-loop  │
             │ A regex+checksum    │  │ (investment/     │  │ Analyst Console│
             │ B LLM/JSON contextual│ │  judol/phishing) │  │ (escalations,  │
             │ C IndoBERT NER      │  └─────────┬────────┘  │  confirm entity)│
             │ → reconcile+confidence│           │          └────────────────┘
             └───────────┬─────────┘  ┌─────────▼────────┐
                         │            │ Syndicate        │
                         └───────────►│ Clustering       │
                                      └─────────┬────────┘
                    ┌───────────────────────────▼──────────────────────────┐
                    │  Intelligence DB (Postgres + RLS, JSONB transcripts)  │
                    │  accounts · wallets · phones · urls · syndicates ·    │
                    │  sessions · messages · entities(provenance,confidence)│
                    └───────────────────────────────────────────────────────┘
```

### 1. Channel Adapter (transport, POC/LIVE boundary) — TEXT + VOICE (both first-class)
- Interface `ChannelAdapter.receive() / .send(msg)` normalizing every channel to an internal
  turn-based `Message` schema, so the agent loop is transport-agnostic.
- **Text adapters** — POC: scripted/replayed scammer transcripts (safe, demo-able). LIVE: Telegram
  (Telethon / Bot API), WhatsApp (Cloud API or web bridge), investment forums.
- **Voice adapters (first-class, see §1a)** — POC: replayed scam-call audio / TTS-synthesized scripted
  caller. LIVE: WhatsApp/PSTN calls via a telephony bridge, engaged in real time.
- All channels gated under Polri supervision in LIVE. All I/O (text turns **and** audio segments +
  transcripts) passes through the **Custody Log** first (hash + immutable timestamp, append-only).

### 1a. Voice subsystem (STT → agent loop → TTS)
Real-time call-baiting. Scammers escalate chat → WhatsApp/phone calls, and voice yields more (live
pressure tactics, caller-ID numbers, call-recording evidence). Proven by **Apate** (STT→LLM→TTS,
~5-min calls, extracts crypto wallets) and directly **reuses OLAF's voice bidi-streaming pipeline**
(turn management, duplicate-suppression, defensive stream close).

- **Pipeline (default = modular, provider-swappable):** inbound audio → **STT** → same Conversation
  Orchestrator (§3) → reply text → **TTS** → outbound audio. Keeping STT/TTS modular preserves LLM
  provider flexibility (via the LiteLLM gateway) and lets us pick **Indonesian-capable** STT/TTS.
  *Option:* Gemini Live **native-audio bidi** (OLAF's exact approach) for lowest latency where its
  provider coupling is acceptable — selectable per deployment.
- **STT/TTS as adapters (POC/LIVE):** STT — Whisper / Google STT / Deepgram (Indonesian + regional
  accents). TTS — ElevenLabs / Google TTS (natural Bahasa voice). Behind adapter interfaces so they
  swap by config; POC can stub with canned audio.
- **Human-realism for voice:** natural prosody, hesitations/fillers ("ehh…", "sebentar ya"),
  believable latency, Bahasa + regional accent. **Synthetic-voice detection is the #1 challenge**
  (Apate's finding) — prioritize voice naturalness + barge-in handling.
- **Real-time human-in-the-loop:** analyst can monitor a live call and **take over (barge-in)** at
  high-value or bot-probe moments — harder than text HITL, so build takeover into the streaming layer
  (reuse OLAF's bidi task structure).
- **Voice-specific custody & evidence:** store the **call recording (audio)** + STT transcript +
  timestamps + diarization, all hashed. Call recording of scammers under Polri supervision is
  defensible under the same reactive/victim-framed rule; recorded audio strengthens evidentiary value.
- **Entity extraction on voice:** STT transcript feeds the **same hybrid pipeline** (§5); expect more
  STT noise on account/wallet numbers → lean harder on Layer-B LLM contextual repair + read-back
  confirmation ("jadi rekeningnya 1-2-3…, betul?") and always validate through Layer-A checksums.

### 2. Persona Engine
- **Structured persona schema** (not a paragraph): name, age, occupation, tech-literacy (low),
  financial situation (plausibly baitable), region/dialect, emotional state, backstory facts,
  channel register (WA/TG shorthand). A **persona pool** for volume + variety.
- Rendered into the system prompt via template + state interpolation (**OLAF pattern**).

### 3. Conversation Orchestrator (agent loop)
- **Thin custom loop (a few hundred lines we own) calling a provider-agnostic LLM gateway**
  (self-hosted **LiteLLM**, OpenAI-compatible). Per turn: load persona + conversation state +
  extraction checklist + running summary → call the gateway with forensic system prompt + tools →
  dispatch tools → persist state.
- **Tiered model routing** (cost + quality): cheap/free tier (Gemini Flash / Jatevo open models) for
  rapport/filler turns — the high-volume bulk; strong tier (**Claude**) for the disclosure-critical
  "which account?" turns + structured entity extraction. Routing policy lives in the gateway
  (lowest-cost / custom), so providers swap by config. LIVE prefers **Jatevo** (Asia-hosted →
  data locality); POC can use OpenRouter / free tiers.
- **Tools (covert side-effect pattern from OLAF's `flag_emotional_distress`)** — silent to the
  scammer: `record_entity(type, value, context)`, `flag_scam_signal`, `update_syndicate_link`,
  `note_disclosure_progress`, `escalate_to_analyst`. No tool can send money/PII or touch external
  systems (legal gate).
- **Dialogue policy staging:** rapport → feign interest/panic → the "kirim ke rekening yang mana?"
  money question. Soft nudges when the extraction checklist is unfilled.
- **Anti-detection prompt discipline:** forbid meta/assistant-speak ("As an AI…", refusals), cap
  message length, allow confusion/being-wrong, persona may not know things.
- **Guardrails:** detect "are you a bot?" probes → escalate to human; never propose new crimes; never
  actually agree to send funds/PII. Provider-abstracted so we can swap/fine-tune later.

### 4. Human-Realism Layer (outside the LLM — #1 anti-detection lever)
- Randomized response delays (minutes–hours), typo/autocorrect artifacts, activity gaps
  ("sorry was at work"), read-receipt timing, **Bahasa Indonesia + regional code-switching**
  (Javanese/Sundanese fillers), WA/TG register. Applied at send time.

### 5. Entity Extraction Pipeline (hybrid, always validated)
- **Layer A — regex + validators/checksums** (high precision, cheap): crypto wallets (BTC bech32/legacy,
  ETH `0x…` + checksum, **TRON `T…` — prioritize USDT-TRC20**), phones (`+62`/`08xx` → E.164), URLs
  (defang, resolve shorteners), **bank accounts** (digit-runs + **bank-name context anchors** BCA/
  Mandiri/BRI/BNI + keywords rekening/norek/a.n./transfer ke — no checksum exists so context is
  mandatory).
- **Layer B — LLM/JSON extraction** for obfuscated/contextual entities ("account eight-one-two…",
  split across messages, "the account I mentioned") + **relationship extraction** (who controls which
  account). Anthropic structured output.
- **Layer C — fine-tuned IndoBERT NER** (IPerFEX / BiLSTM-CRF) for person/org/alias → feeds clustering.
- **Reconciliation:** dedupe → cross-validate every Layer-B output through Layer-A validators →
  confidence-score → provenance-log (message_id, turn, method). Un-validated LLM entities are never
  stored as actionable.

### 6. Crime Classifier
- Classifies the conversation: investment scam / online-gambling (judol) deposit / crypto phishing /
  romance / other. LLM classifier + validation. Target **>80% accuracy** (proposal KPI).

### 7. Syndicate Clustering
- Clusters accounts/wallets/phones/aliases/linguistic-fingerprints/temporal-patterns into **syndicate
  profiles**. Graph-based (shared accounts, phone reuse). Feeds Intel DB + hands off to TAKEDOWN graph.

### 8. Intelligence DB (Postgres + RLS)
- Tables: `scam_sessions`, `messages` (raw, hashed), `entities` (type, value, provenance, confidence,
  review_status), `accounts`, `wallets`, `phones`, `urls`, `syndicates`, `classifications`. JSONB for
  transcripts/metadata. **RLS-scoped** by agency. Address/wallet entities flow into TRACE/TAKEDOWN.

### 9. Chain-of-Custody & Evidence
- Append-only SHA-256-hashed raw message log, immutable timestamps; preserved originals separate from
  enriched data; per-entity provenance chain; documented model/prompt/version manifest per session;
  full analyst audit trail. Everything reproducible + explainable for court.

### 10. Human-in-the-Loop Analyst Console (frontend)
- Live sessions, escalation queue, confidence-scored entity confirmation, one-click takeover at
  high-value turns, disinformation flagging. **Reuse ELSA's "Glass Box" reasoning-trace UI** — it
  already renders each tool call, its args, and timing; near-perfect for a forensic audit console.

### 11. Safety / Abuse Controls
- Access control + audit on the agent itself, abuse monitoring, kill switch, and enforcement of the
  reactive-only legal guardrails. Treated as sensitive infrastructure.

---

## Data flow (one inbound turn)

inbound scammer msg → Channel Adapter normalize → **Custody Log (hash + ts)** → Orchestrator
(persona + state + tools) → Claude → tools record entities/flags (covert) → Extraction pipeline
(A/B/C → reconcile → confidence + provenance) → Intel DB → Classifier + Clustering update →
outbound reply drafted → **Human-Realism Layer** (or Human-in-the-loop if high-value) → Channel
Adapter send → **Custody Log**.

---

## Reuse map for INFILTRATE

| Piece | Source | Action |
|---|---|---|
| Agent + tools scaffolding, persona-as-instruction-string + `{state}` interpolation | OLAF | **Reuse pattern** (re-implement on Anthropic SDK) |
| Covert side-effect tool (`flag_emotional_distress` → `record_entity`/`escalate`) | OLAF | **Reuse pattern** — ideal fit |
| Structured JSON extraction (schema-constrained output) | OLAF | **Reuse pattern** for entity extraction |
| FastAPI skeleton, pydantic-settings config, docker-compose, CI | OLAF | **Reuse** |
| Voice bidi-stream runner (STT→LLM→TTS, turn mgmt, duplicate-suppression, defensive close) | OLAF | **REUSE (first-class)** — powers the voice channel (§1a); pair with the text `run()` loop for chat |
| Firebase Auth / Firestore | OLAF | **Drop** — we use JWT + Postgres RLS |
| Gemini / Google ADK | OLAF | **Drop ADK**; re-implement thin loop against a **LiteLLM gateway** (Anthropic/Gemini/Jatevo/OpenRouter swappable, tiered routing) |
| Glass Box reasoning-trace UI | ELSA | **Reuse** for the analyst console / custody view |
| Messaging channels (Telegram/WhatsApp), scam-entity NER, syndicate clustering, chain-of-custody | — | **Build new** (net-new core) |

---

## Risks & mitigations (from research)

| Risk | Mitigation |
|---|---|
| Bot detection → data poisoning (fake accounts fed to us) | Confidence scoring + corroboration before actionable; human-in-loop; realism layer |
| Low yield / high volume needed (<49% takeoff, ~32% IDR) | Persona pool + concurrent sessions via Dramatiq; benchmark vs 2509.08493 |
| Dual-use weaponization | Access control, audit, abuse monitoring, kill switch |
| Hallucinated / fabricated entities contaminate evidence | Always validate LLM output through Layer-A validators/checksums |
| Legal overreach (entrapment / UU ITE) | Reactive-only prompt + tool-gating; never access systems or redistribute data |
| Evidence challengeability | Engineered chain-of-custody; documented, reproducible pipeline |
| Bahasa/timing realism gap (top practical tell) | Human-realism layer + regional code-switching + (optionally) fine-tuned model |
| Synthetic-voice detection on calls (Apate's #1 challenge) | Natural prosody/fillers, believable latency, Bahasa accent TTS, barge-in HITL takeover |
| STT errors on spoken account/wallet numbers | Layer-B LLM contextual repair + read-back confirmation + Layer-A checksum validation |
