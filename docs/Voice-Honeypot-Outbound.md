# ITTU — Voice Honeypot: Outbound Calling (design spec)

**Status:** phases 1–4 + 6 **shipped** (data model, case "Calls" list, Numbers/Campaigns CRUD
+ Honeypot Ops UI, the POC-simulated dial worker with Requeue and the CDR call log, and the
triage queue + case linking). **Phase 5 — the real Twilio `PstnChannelAdapter` + WebSocket
media bridge — is the remaining piece**, and the only one needing a Twilio account; dialing
*real reported numbers* additionally stays behind the Polri gate (§0). Everything shipped so
far simulates: nothing has ever placed a call.

This is the **single reference** for the outbound voice-honeypot MVP — every phase below can
be handed to a specialist agent against this doc with no further context. Extends
[`Live-Voice-Calls.md`](Live-Voice-Calls.md) (which specs the STT/TTS/media-bridge stubs)
with the **operational layer around calling**: where numbers come from, how a bulk dial list
gets worked, and how a call becomes a case.

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
| `last_error` | text, nullable | last attempt's failure reason |
| `updated_at` | timestamptz | |

> **⚠️ `session_id` is being REMOVED (decided 2026-08-16).** Phase 1 shipped a nullable
> `dial_targets.session_id` FK, which assumed one call per target. With **Requeue** (§3.6) a
> target is dialed repeatedly, so target→sessions is **one-to-many** and a single FK can only
> hold "first" or "latest" — ambiguous either way. The reverse FK
> `scam_sessions.dial_target_id` already carries the full history, so `session_id` is
> redundant. **Phase 4 must drop it** (and the mutual-FK `use_alter` dance Phase 1 needed
> along with it). Do this before any code depends on it.

### 3.3b `honeypot.dial_attempts` — the call log (CDR), one row per ATTEMPT

**Added 2026-08-16 (migration `20260816_15`)**, closing a gap in phase 4: the dialer
originally recorded a call only when it *connected*, so a no-answer or carrier failure left
no per-attempt trace at all (`attempt_count` is a bare counter; `status`/`last_error` hold
only the latest value). "Tried three times: no answer at 14:03 and 16:20, engaged at 09:12"
was unreconstructible — and "never picks up" is itself intel about a target.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `target_id` | uuid FK → `dial_targets` (CASCADE) | indexed |
| `attempt_no` | int | mirrors the target's `attempt_count` at the time (1-based) |
| `outcome` | text | `engaged` \| `no_answer` \| `failed` |
| `error` | text, nullable | carrier/transport reason on failure |
| `duration_seconds` | int, nullable | 0 when nobody answered |
| `session_id` | uuid, nullable FK → `intel.scam_sessions` | set ONLY for `engaged` — the conversation this attempt produced |
| `data_mode` | text | POC attempts must never read as engagement evidence |
| `started_at` | timestamptz | |

`UNIQUE (target_id, attempt_no)` makes the actor's logging idempotent under Dramatiq's
at-least-once redelivery. RLS policies the row two hops out (attempt → target → campaign),
the same join-don't-denormalize choice §3.3 made — an un-policied table here would expose
who every other agency has been calling.

`session_id` lives here, not on `dial_targets` where §3.3 correctly removed it: on an
attempt row it is unambiguous, because a row *is* one attempt.

### 3.4 New columns on `intel.scam_sessions` (voice/call-specific)

**One `scam_sessions` row per *connected* attempt** — the conversation, with its transcript,
extracted intel and custody chain. Not every attempt: a no-answer has no transcript and no
intel, and the triage queue (§5) reads sessions as an analyst work queue, so filling it with
silent attempts would make it a chore to work. Those attempts are logged in
`honeypot.dial_attempts` (§3.3b) instead.

**The two logs together:** requeue a target and dial again → a second `dial_attempts` row
always, plus a second `scam_sessions` row if that attempt connected.

| Column | Type | Notes |
|---|---|---|
| `duration_seconds` | int, nullable | call length |
| `recording_url` | text, nullable | audio location — **deferred, see §3.7**; empty until then |
| `disposition` | text, nullable | `engaged` \| `no_answer` \| `hung_up` \| `voicemail` |
| `dial_target_id` | uuid, nullable FK → `honeypot.dial_targets` | **the call-log link** — many sessions per target |

`case_id` and `channel_ref` already exist — this is additive only.

### 3.6 Requeue (call the same number again)

Numbers are deduped **within a campaign** (a repeat in one paste is an accident, and an
accidental double-call from a police tool is not recoverable). Re-calling is served two ways:

- **A new campaign** — already works today; cross-campaign upload is never rejected.
- **Requeue (to build in phase 4)** — reset ended targets (`no_answer` / `failed`, optionally
  `engaged`) back to `queued`, per-target or bulk ("requeue all no-answers"). `attempt_count`
  is preserved as retry history; the next dial appends a `dial_attempts` row (§3.3b) — plus a
  `scam_sessions` row if it connects.

Duplicate target ROWS are deliberately never created: they would make per-status counts
meaningless ("2 no_answer" = two numbers, or one number twice?) and break "was this number
called?". The `already_in_campaign` reject message should point at Requeue, not read as a
dead end.

### 3.7 Call recording — DEFERRED (decided 2026-08-16)

**The transcript is already saved for free and is the primary evidence.** Our own STT feeds
the agent loop, and every utterance lands in `intel.messages` — SHA-256 hash-chained for
custody. So a call is already fully logged and court-reproducible without any audio.

Audio recording is wanted **later**, and when we add it there are two routes:

| | Twilio recording | Self-recorded from Media Streams |
|---|---|---|
| Cost | ~$0.0025/min record + ~$0.0025/min storage (≈1–2¢ per 5-min call); transcription $0.05/min (we don't need it — we have STT) | No Twilio fee; our own storage only |
| Effort | Trivial (a flag + fetch the URL) | Must persist the μ-law/8kHz frames we already receive, encode, and store |
| Custody | Audio lives at a third party | **Audio stays in our own evidence chain** |

**Preference when we build it: self-recorded.** Twilio's Media Streams already sends us the
call audio (that's how STT works), so writing it to our own storage costs no per-minute fee
*and* keeps the evidence in our custody chain rather than a third party's — which matters
more than the money for a court-bound forensics tool. Twilio recording stays the quick
fallback if self-recording proves fiddly.

⚠️ **Recording is not merely a technical choice**: lawful recording/interception of a real
suspect is part of what **Polri authorization** must cover (§0). Self-test calls are
unaffected.

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
**promote to new case** (creates through the same `CaseRepository` the Cases API uses, then
attaches — a promoted case is indistinguishable from a hand-made one).

**As built** (`app/honeypot_ops/triage.py`, `dialer.resolve_case_id`):

* Matching lives in `resolve_case_id`, called when the dialer creates a session. It takes
  `entity_values` for the wallet/account arm, but the POC dialer passes none — a *simulated*
  call has no transcript, so there is nothing extracted at that instant. The phase-5 media
  bridge is what will supply them for a real call; the number arm works today.
* Entity matching is restricted to `crypto_wallet | bank_account | phone`. `url` is
  deliberately excluded: scammers reuse the same phishing kit across unrelated operations, so
  a shared link identifies the kit, not the syndicate.
* Every match is scoped to the calling agency. The dialer runs as the owning role (a system
  actor is handed a row id and must read it to learn the owner), so RLS is *not* protecting
  this query — the explicit `agency_id` filter is the only thing preventing a cross-agency
  link, and it is asserted directly in `test_honeypot_dialer_pg.py`.
* Triage owns no storage in either mode: under Postgres it queries `intel.scam_sessions`;
  in memory it is a view over the INFILTRATE memory store, so a session created by the
  honeypot console appears in triage with no syncing between two stores.
* Attaching writes exactly one column on one row rather than going through
  `InfiltrateRepository.save_session()`, which upserts the whole session *and*
  unconditionally inserts a `CrimeClassification` — attaching would have silently duplicated
  the classification every time.
* Promote prefills title (number + date), crime type (from the classifier) and a summary
  naming the originating session; any field can be overridden in the request body.

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
| `POST` | `/honeypot/campaigns/{id}/requeue` | send finished targets back to `queued` (§3.6) |
| `GET` | `/honeypot/targets/{id}/attempts` | the call log for one target (§3.3b) |
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
   pacing/retry/status machinery without touching Twilio. **Also in this phase:** drop the
   now-ambiguous `dial_targets.session_id` (§3.3), create one `scam_sessions` row per
   attempt (§3.4), and add **Requeue** (§3.6).
5. **`PstnChannelAdapter` (Twilio) + media bridge** — this is `Live-Voice-Calls.md`'s
   scope (streaming STT/TTS + WS bridge + TwiML). Once built, `dial_target` in LIVE mode
   calls into it for real. **Test only against self-verified/demo numbers.**
6. **Triage + case-linking** (§5) — layers on top of 1–5; can be built in parallel with 5
   since it only needs sessions to exist (POC-simulated sessions are enough to build/test it).

Phases 1–4 and 6 need **no Twilio account and no legal gate** — fully buildable and
demoable now. Phase 5 is the one requiring Twilio credentials and is where the
self-test-only line matters.

**Phase 5 partial (shipped 2026-08-17)** — `app/infiltrate/telephony.py` +
`POST /api/telephony/voice`: webhook **signature validation** (fails closed; the HMAC is
the only auth this endpoint has), TwiML builders, and a REST client that fails loud
without credentials. The answer webhook speaks one line and hangs up rather than opening
`<Connect><Stream>`, because pointing Twilio at an unbuilt media bridge connects a real
caller to silence. Setup + how to verify it by ringing the number:
[`Live-Voice-Calls.md`](Live-Voice-Calls.md) → *Twilio setup*. Still outstanding: the WS
media bridge, streaming STT, turn-taking/barge-in.

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
- **Call log → ONE `dial_attempts` ROW PER ATTEMPT (one-to-many).** Every attempt is logged
  in `honeypot.dial_attempts` (§3.3b), including the ones nobody answered; a *connected*
  attempt additionally gets an `intel.scam_sessions` row for the conversation (§3.4).
  `dial_targets.session_id` is dropped as ambiguous (§3.3). Requeue (§3.6) is how you call a
  number again — duplicate target rows are never created.
  *(Revised 2026-08-16: phase 4 first logged only connected calls, which silently lost the
  no-answer history. The CDR/conversation split keeps both without making triage a chore.)*
- **Audio recording → DEFERRED, self-recording preferred when built** (§3.7). The
  hash-chained transcript already provides the evidence record at zero cost; when audio is
  added, capturing it from the Media Streams we already consume avoids Twilio's per-minute
  record+storage fee **and** keeps the audio inside our own custody chain. Costs recorded in
  §3.7 for when we revisit.
