# ITTU — Voice Honeypot: Outbound Calling (design spec)

**Status:** design only, nothing built yet. This is the **single reference** for building
the outbound voice-honeypot MVP — every phase below can be handed to a specialist agent
against this doc with no further context. Extends [`Live-Voice-Calls.md`](Live-Voice-Calls.md)
(which specs the STT/TTS/media-bridge stubs) with the **operational layer around calling**:
where numbers come from, how a bulk dial list gets worked, and how a call becomes a case.

**One-liner:** an investigator uploads a list of scammer numbers → the system dials them
from a rotating pool of honeypot numbers → the AI persona engages each call → the
transcript + extracted intel becomes a session that either joins an existing case or
lands in triage for an investigator to assign.

---

## 0. Why outbound, and the legal line (read this first)

Two engagement directions exist; **outbound is the MVP** because it's controllable —
inbound depends on scammers finding a seeded number, which is luck + reach, not
architecture (see `Live-Voice-Calls.md` and the Backlog's gated A2/B2/B3 items for the
inbound/Telegram path).

**The legal line does not move for this feature.** Two distinct cases:

1. **Demo / self-test target** (you call your own verified number, or a consenting
   tester) — zero legal exposure, same as today's `Live-Voice-Calls.md` Tier-A. This is
   what proves the pipeline works and is buildable **now**.
2. **A real reported scam number** — this is engaging a real suspect on a live channel.
   Same gate as `PstnChannelAdapter`/`TelegramChannelAdapter` today: **Polri
   authorization required.** Nothing in this doc removes that gate — the campaign
   feature is built once, but dialing real targets stays blocked behind the same
   `NotImplementedError`-until-authorized posture until that authorization exists.

So: build the whole pipeline against self-test numbers first (fully demoable, no gate).
Flipping it to dial real reported numbers is a **policy switch**, not a rebuild.

---

## 1. Architecture overview

```
                    ┌─────────────────────────────────────────────┐
                    │              Honeypot Ops (new UI)           │
                    │  Numbers · Campaigns · Triage                │
                    └───────────────┬───────────────────────────────┘
                                    │ REST (agency-scoped, RLS)
                                    ▼
   ┌────────────────────────────────────────────────────────────────────┐
   │ Backend: honeypot_ops module (new)                                  │
   │  - honeypot.numbers        (the number pool)                        │
   │  - honeypot.dial_campaigns (an uploaded batch)                      │
   │  - honeypot.dial_targets   (one row per number in the batch)        │
   └───────────────┬──────────────────────────────────┬─────────────────┘
                    │ enqueue                          │ read
                    ▼                                  ▼
          ┌──────────────────────┐         ┌─────────────────────────┐
          │ Dramatiq worker       │         │ Triage queue view        │
          │ dial_target actor     │         │ (sessions, case_id NULL) │
          │ (paced, retried)      │         └─────────────────────────┘
          └──────────┬────────────┘
                     │ places call
                     ▼
          ┌──────────────────────────────────────────────────────────┐
          │ PstnChannelAdapter (Twilio) — Live-Voice-Calls.md          │
          │  Twilio Voice API places the call FROM a pool number       │
          │  TwiML <Connect><Stream> opens the WS media bridge         │
          └──────────┬───────────────────────────────────────────────┘
                     ▼
     Media bridge (WS) ──[WhisperSTTAdapter]──► agent.run_session (EXISTS)
                     ▲                                    │
                     └──────[TTSAdapter: EL/Gemini/Google]─┘
                                                            │
                                                            ▼
                                          ScamSession row (case_id: matched
                                          case OR null → triage)
```

**Everything below the media bridge already exists** (agent loop, extraction, custody
hash-chain, classifier, syndicate clustering, TTS providers). This doc adds: the number
pool, the campaign/dial-list layer, the worker actor that places calls, and the
triage/case-linking step. `Live-Voice-Calls.md` still owns the STT/TTS/media-bridge
build — not duplicated here.

---

## 2. New surface: "Honeypot Ops" menu (not the Control Panel)

The Control Panel (`/settings`) is per-browser analyst preference (localStorage) — voice
provider, call mode. Numbers/campaigns/triage are **shared, agency-scoped, server-side**
operational data with their own lifecycle. New top-level nav item, own route
`/honeypot-ops`, three tabs:

| Tab | Purpose |
|---|---|
| **Numbers** | The Twilio number pool: add/retire, rotation policy, active flag, per-agency ownership |
| **Campaigns** | Upload a dial list (CSV/paste), see progress (queued/dialing/done/failed per target), pause/resume |
| **Triage** | Calls with no matched case — assign to an existing case or promote to a new one |

All three are read/write through a new backend router, RLS-scoped like everything else
(`core.agencies` ownership via `agency_id`).

---

## 3. Data model (new tables — `honeypot` schema)

Mirrors the `action.notifications` pattern (the C1 worker precedent: durable status,
retries, idempotency) and reuses `intel.scam_sessions` as-is — it **already** has
`case_id` (nullable, "may pre-date case"), `channel_type` (`text|voice`), `channel`
(already lists `pstn`/`wa_call` as anticipated values!), and `channel_ref` (the number).
No new session table needed — just new columns on it (see 3.3) and the new upstream
tables that produce sessions.

### 3.1 `honeypot.numbers` — the pool

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `agency_id` | uuid FK → `core.agencies` | owning agency (RLS) |
| `phone_number` | text, unique | E.164, e.g. `+62812xxxxxxx` |
| `twilio_sid` | text | Twilio's number SID (for API management) |
| `label` | text | operator-facing name, e.g. "Bareskrim honeypot #1" |
| `status` | text | `active` \| `retired` \| `rate_limited` |
| `data_mode` | text | `poc` \| `live` (poc = never actually dials Twilio) |
| `created_at` / `updated_at` | timestamptz | |

### 3.2 `honeypot.dial_campaigns` — one uploaded batch

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `public_id` | text, unique | `camp_...` |
| `agency_id` | uuid FK | |
| `name` | text | operator label |
| `case_id` | uuid, nullable | optional: pre-attach the whole campaign to one case |
| `status` | text | `draft` \| `running` \| `paused` \| `completed` |
| `pacing_per_minute` | int | dial-rate cap (Twilio concurrency limits) |
| `created_by` | uuid, nullable FK → `core.users` | |
| `created_at` | timestamptz | |

### 3.3 `honeypot.dial_targets` — one row per number in a campaign

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `campaign_id` | uuid FK → `dial_campaigns` | |
| `phone_number` | text | E.164, deduped within a campaign |
| `status` | text | `queued` \| `dialing` \| `no_answer` \| `engaged` \| `failed` |
| `attempt_count` | int, default 0 | mirrors `notifications.attempt_count` |
| `last_error` | text, nullable | |
| `session_id` | uuid, nullable FK → `intel.scam_sessions` | set once the call connects |
| `updated_at` | timestamptz | |

### 3.4 New columns on `intel.scam_sessions` (voice/call-specific)

| Column | Type | Notes |
|---|---|---|
| `duration_seconds` | int, nullable | call length |
| `recording_url` | text, nullable | Twilio recording (evidence — same custody principle as `evidence_manifest`) |
| `disposition` | text, nullable | `engaged` \| `no_answer` \| `hung_up` \| `voicemail` |
| `dial_target_id` | uuid, nullable FK → `honeypot.dial_targets` | back-reference for campaign reporting |

`case_id` and `channel_ref` already exist — this is additive only.

### 3.5 Migration
One new migration: `add honeypot schema (numbers, dial_campaigns, dial_targets) +
scam_sessions call columns`, RLS policies on the two agency-scoped tables mirroring
`core.cases`'s existing policy shape. Follows immediately after whatever is head at
build time — **run the migration-drift guard's `alembic upgrade head` before testing**
(the guard added this session will refuse to boot if this is forgotten).

---

## 4. Worker: `dial_target` Dramatiq actor

Mirrors `dispatch_notifications` (`app/uncover/notifications.py`) exactly:

```python
@dramatiq.actor(max_retries=<N>, min_backoff=<ms>)
def dial_target(dial_target_id: str) -> None:
    """Place one outbound call for a queued dial target, paced + retried."""
    asyncio.run(_dial_one(dial_target_id))
```

- Enqueued when a campaign is started (`status: draft → running`), respecting
  `pacing_per_minute` (a scheduling gate before `.send()`, or a rate-limited queue
  consumer — exact mechanism is an implementation choice, not a design constraint).
  Twilio's own per-account concurrency cap is the hard ceiling regardless.
- On call connect → creates a `ScamSession` (case_id = campaign's `case_id` if set,
  else attempt the match in §5, else `NULL` = triage) and links `dial_targets.session_id`.
  Same call also wires the session into `PstnChannelAdapter` for the live media bridge.
- On failure (busy/no-answer/Twilio error) → `attempt_count++`, `last_error` set,
  requeued up to the retry budget — same durable-row-status pattern as C1.
- **`data_mode` gate**: in POC, `dial_target` never calls Twilio — it simulates a result
  (deterministic no-op or a scripted outcome) so campaigns are demoable with zero cost
  and zero real dialing, exactly like every other POC/LIVE boundary in this codebase.

---

## 5. Call → session → case linking

On every connected call, before creating the `ScamSession`:

1. **Campaign has `case_id` set** → attach directly, done.
2. **Else, try to match**: does `phone_number` already appear as a `channel_ref` on an
   existing session attached to a case? Does any wallet/account extracted from *this*
   call match an existing case's entities (via the same extraction pipeline that already
   runs mid-session)? If either matches → attach to that case.
3. **Else → `case_id = NULL`** → the session appears in **Triage**.

Triage view = `SELECT * FROM intel.scam_sessions WHERE case_id IS NULL AND
channel_type = 'voice'` (agency-scoped), each row showing transcript preview + duration +
any extracted entities, with two actions: **attach to existing case** (search/pick) or
**promote to new case** (calls the existing `POST /cases` you already have, then attaches).

This makes the existing **syndicate clustering** the thing that quietly does most of the
real linking work over time — once two triaged sessions share a wallet, they cluster,
which is a strong hint they're the same case even before a human confirms it.

---

## 6. API surface (new `honeypot_ops` router, `/api/honeypot`)

| Method | Path | Purpose |
|---|---|---|
| `GET/POST` | `/honeypot/numbers` | list / add a pool number |
| `PATCH` | `/honeypot/numbers/{id}` | retire / relabel |
| `GET/POST` | `/honeypot/campaigns` | list / create a campaign |
| `POST` | `/honeypot/campaigns/{id}/targets` | bulk-upload numbers (CSV body or JSON array) |
| `POST` | `/honeypot/campaigns/{id}/start` \| `/pause` | lifecycle control |
| `GET` | `/honeypot/campaigns/{id}` | progress rollup (counts by target status) |
| `GET` | `/honeypot/triage` | unmatched voice sessions |
| `POST` | `/honeypot/triage/{session_id}/attach` | `{case_id}` — attach to existing |
| `POST` | `/honeypot/triage/{session_id}/promote` | create + attach a new case |

All behind `get_current_user`, agency-scoped like `cases/router.py`.

---

## 7. Frontend surface

New `/honeypot-ops` route + nav entry, three tabs matching §2. Reuses existing UI
primitives (the case-page's transcript viewer, the settings page's table/list patterns).
Campaign upload = a CSV/paste textarea → client-side E.164 validation → POST. Triage row
expand reuses the transcript component already built for case sessions.

**Also, from the earlier conversation**: the case detail page should grow a
**"Calls / Conversations"** section listing every session on the case (number, date,
duration, disposition, entity count) — this is a small addition since `rollup.sessions`
already carries this data (`cases/router.py:118`); today only counts are shown, not the
list. Worth doing regardless of campaign work, since it's needed either way once multiple
calls attach to one case.

---

## 8. Build order (phase-able, hand each phase to one agent)

1. **Data model** — the migration (§3), ORM models, RLS policies. No behavior yet.
2. **Case detail: sessions list** (§7 second half) — small, independent, ship first for
   immediate value (today's rollup already has the data).
3. **Numbers + Campaigns CRUD** (backend + `Honeypot Ops` UI, §2/§6/§7) — no dialing yet,
   just the pool + upload + list management. Demoable with fake/simulated data.
4. **`dial_target` worker actor in POC mode** (§4) — simulated dialing, proves the
   pacing/retry/status machinery without touching Twilio.
5. **`PstnChannelAdapter` (Twilio) + media bridge** — this is `Live-Voice-Calls.md`'s
   scope (streaming STT/TTS + WS bridge + TwiML). Once built, `dial_target` in LIVE mode
   calls into it for real. **Test only against self-verified/demo numbers.**
6. **Triage + case-linking** (§5) — layers on top of 1–5; can be built in parallel with 5
   since it only needs sessions to exist (POC-simulated sessions are enough to build/test it).

Phases 1–4 and 6 need **no Twilio account and no legal gate** — fully buildable and
demoable now. Phase 5 is the one requiring Twilio credentials and is where the
self-test-only line matters.

---

## 9. Decisions (settled 2026-08-16)

- **Number provisioning → REGISTER, don't provision.** Numbers are bought/configured in
  the Twilio console; our app stores number + `twilio_sid` + label (the §3.1 schema
  already holds this — no rewrite if we automate later). Rationale: API provisioning
  means number search + purchase (real money) + webhook config + release — a subsystem
  for something done a handful of times, and it keeps *spending money* a deliberate
  human action rather than something an app can do in a loop.
- **Auto-match strength → EXACT MATCH ONLY.** Attach a call to a case only on an exact
  wallet address / bank account / phone-number hit (§5 step 2). Everything else goes to
  triage. Rationale: a false auto-match silently contaminates a case file destined for
  court — far worse than 10 seconds of investigator triage. Widen later against real
  triage volume, not speculation.
- **Streaming STT provider → DEFERRED to phase 5** (doesn't block phases 1–4/6). When we
  get there, benchmark hosted streaming STT (Deepgram / Google STT — both do id-ID, no
  GPU to run) against self-hosted Whisper **on real Indonesian call audio**: Bahasa
  accuracy + latency under live conditions decide it, and neither is predictable from
  docs. Choosing now would be a guess.
