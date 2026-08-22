# ITTU — Backlog

> The single **"what are we aiming for"** board. Keep it current — check items off as they ship.
> This is the short prioritized list; full rationale, effort, and triggers live in
> [`Production-Roadmap.md`](Production-Roadmap.md). Status legend: S/M/L = small/medium/large effort.

_Last updated: 2026-08-22 · branch `feat/c1-notifications-delivery`._

---

## 🩹 Fixed this cycle (worth remembering — both were silent failures)
- [x] **DB migration drift → broke "create case"** (2026-08-15) — the Neon DB was 3 migrations behind, so
      `core.cases` had no `stage` column and every insert 500'd with nothing pointing at the cause. Fixed by
      `alembic upgrade head`; **prevented** by a boot guard that refuses to start when the schema is behind
      (`app/core/migration_guard.py`) plus CI integrity tests (single-head + apply-chain canary).
- [x] **`casedata` grants missing for `ittu_app`** (2026-08-16, `6d93896`) — `create_app_role.sql` granted
      every schema except `casedata`, so under Postgres persistence the analyst-entered bank-account /
      crypto-transfer features hit `InsufficientPrivilege` with no hint. Verified DENIED→ACCESSIBLE on the
      live DB; grants applied and the script fixed for fresh environments.

## ✅ Done — core is feature-complete
All four pillars + honeypot (text **and** live-mic voice), Response dashboard, and the case-centric
hub. Live blockchain tracing (async jobs, hardened, cycle-fix). Auth/RLS + Google OAuth. LLM brain
live in prod. Persistence (Postgres/Neon, dual in-memory/Postgres repositories). **C1 dispatch
delivery** — production-ready notification layer (HMAC-signed webhooks, idempotency keys, durable
retried delivery via the Dramatiq actor, `GET /api/notifications` outbox feed + retry, Dispatch Log
on the Response dashboard). **493 backend tests green**, frontend build green.

## 🟢 Actionable now — buildable today (no external gate)
- [x] **B1 — TTS (ElevenLabs)** · S · **DONE (2026-08-08)** — code path complete end-to-end: the
      `ElevenLabsTTSAdapter` synthesizes real audio, the `/audio/{seq}` endpoint now **serves the bytes**
      (was discarding them), cached to avoid re-paying the provider, and degrades to browser speech if
      synthesis fails. **Only remaining step is operational:** set `ITTU_TTS_PROVIDER=elevenlabs` +
      `ITTU_ELEVENLABS_API_KEY` on Render and flip the Control Panel to hear the natural voice (the
      demo's wow moment). Keyless POC still uses browser TTS.
- [x] **C1 — Notifications** · ~~S~~ M · **DONE (2026-08-08)** — built production-ready, not a demo
      shim: signed + idempotent + retried LIVE delivery (`ITTU_NOTIFICATION_DELIVERY=worker`),
      agency outbox feed, POC mock path unchanged. Flip `ITTU_MODE=live` + set the webhook URL/secret
      to dispatch for real.
- [x] **UAM — user access management** · M · **DONE (2026-08-22)** — `GET/POST /api/users`,
      `PATCH /api/users/{id}`, plus a `/users` screen. Provisioning people no longer means editing
      the `ITTU_OAUTH_PROVISION` allowlist and redeploying.
      The gap it closed was worse than "no admin UI": `core.users.is_active` had existed since
      migration 09 and **nothing read it** — there was no way to revoke anyone's access at all.
      Guards, each because the failure is unrecoverable from inside the product: an agency-admin
      cannot create or grant `platform-admin` (privilege escalation), cannot touch another agency,
      cannot deactivate or demote themselves, and the last active admin of an agency cannot be
      removed. Every mutation is audited under the **target** agency's chain, noting the acting
      agency when a platform-admin reached in.
      **Known limit, stated in the API and the UI:** request auth is pure JWT and never reads the
      database, so under Postgres a deactivated user's existing token keeps working until it expires.
      Login is blocked immediately; the TTL is the mitigation — so the TTL was cut **8h → 1h**
      (`ITTU_JWT_TTL_SECONDS`, default 3600), bounding the revocation window at one hour.
      That is a deliberate trade, not a fix: with no refresh flow, every expiry is a real re-login,
      so `/login` now explains an involuntary bounce ("Your session expired") instead of silently
      swapping the screen. Sub-hour revocation would need a per-request `is_active` lookup
      (~1 query/request) or short TTL + refresh — **not built**, and worth revisiting if a
      compromised-account drill ever needs to be measured in seconds.

- [ ] **A1-prod — Dramatiq executor swap** (investigation jobs) · S–M · *deferred by choice* — async
      already works in-process; build only when there's real concurrency (submit→poll contract is a
      drop-in). *(Note: C1 already stood up the Dramatiq delivery actor + broker for notifications.)*
- [x] **Wallet risk scoring — rules specified, and the model improved** · M · **DONE (2026-08-18)**
      — spec: [`Wallet-Risk-Scoring-Rules.md`](Wallet-Risk-Scoring-Rules.md). Every constant is
      documented and honestly marked *unvalidated default*; band→action mapping proposed; validation
      plan in §5.
      Writing the spec forced working out what the rules *implied*, which surfaced a real defect:
      **an OFAC-sanctioned wallet with no detected pattern scored LOW**, with the output
      contradicting itself (reasoning named the SDN listing, band said low). Then researching how
      established tools score wallets showed a **structural** gap — they score *counterparty
      exposure* (who you transacted with, hop-decayed, value-weighted, category-severity) and we had
      none of it, so a first-hop mule with no laundering pattern of its own also scored LOW.
      Both fixed in **v0.2.0** (`911ee9a`): sanctions are a band FLOOR, and `app/takedown/exposure.py`
      adds counterparty exposure. On our own fixtures the fan-out mules moved LOW → medium/high.
      `MODEL_VERSION` bumped so older scores stay attributable; Glass Box names the new signals
      (`sanctions_check()`, `counterparty_exposure()`).
      **Still open** (needs data or a human, not code): validate the constants against labelled cases
      (§5 — precision/recall *per band*, ±20% sensitivity), confirm the band→action mapping with
      investigator practice, and assign an owner for the numbers. Related: `wallet_risk_scores.wallet_id`
      nullability is a product decision to settle at the same time.
- [ ] **Go-live hardening** · M · *partly done* — only fully needed when heading to real production.
      - [x] **Contract tests per LIVE adapter** — `tests/test_live_adapter_contract.py` asserts the
            "fail loud, never silently degrade" invariant over the registry, so a new adapter cannot
            silently no-op.
      - [x] **Security + RLS-isolation review** (2026-08-18) — found and closed a real cross-tenant
            leak in two join tables; method and findings in `Security-Evidence.md` §9.
      - [x] **Observability: readiness diagnostics** — `GET /ready` (`app/core/health.py`) probes the
            database, migration head, schema grants, whether RLS is genuinely enforcing, and Redis;
            503 when a critical check fails so it can back a probe. `/health` stays shallow on
            purpose. Each check exists because that failure previously cost real debugging time.
            See `Deploy.md` §7.
      - [ ] **Observability: the rest** — metrics (request rate/latency/error counters), uptime
            monitoring + alerting on `/ready`, and log correlation ids. `/ready` answers "why is it
            broken *right now*"; none of this yet answers "was it broken at 3am" or "is it degrading".
      - [ ] Separate DB per mode (POC vs LIVE evidentiary isolation).
- [ ] **Audit trail — broaden & surface** · M · **backend slice DONE (2026-08-17, `7507034`)** —
      roadmap step 2's "chain-of-custody end-to-end". `core.audit_log` was migrated and documented as
      hash-chained but **nothing ever wrote to it**; `app/core/audit.py` is now the writer (per-agency
      SHA-256 chain, never raises — audit must not break the action it records) and `GET /api/audit`
      reads it, **verifying the chain on read** and reporting `broken_at_seq`. Tests prove tampering
      and deletion are both *detected*, not just that rows appear.
      - [x] Writer + per-agency chain + read API + verification
      - [x] Wired (all 7): `auth.login`, `case.created`, `case.updated`, `entity.reviewed`,
            `dispatch.sent`, `triage.attached`, `triage.promoted`. `case.updated` logs only the
            changed fields; `dispatch.sent` names recipient agencies but never the payload or secret.
      - [x] UI: `/audit` (`d1935cf`) — chain verification is the FIRST thing on the page, since a
            tamper-evident log nobody checks proves nothing.
      - [x] Durable coverage of evidence generation — `action.bundle.generated` (with document
            sha256s) and `dispatch.sent` now land in the core trail (2026-08-18).
      - [x] Origin + export auditing (2026-08-18) — after checking practice against CloudTrail /
            SOC 2 guidance: entries now record `_ip`, `_user_agent` and `_request_id` (who acted
            **and from where**, and which log line it belongs to), and `evidence.exported` audits
            document downloads with the custody hash. Evidence could previously leave the system
            with no trace at all — the top insider-risk question in forensics.
      - [x] **Audit DENIED actions too** · S · **DECIDED + DONE (2026-08-22)** — *raised
            2026-08-18.* Adopted: denials by an **authenticated** actor are recorded.
            `record_denial()` in `app/core/audit.py`. Failed logins and 401s stay OUT (brute-force
            noise belongs in security logging, not an agency's evidentiary chain a court has to
            read); so does the Twilio webhook 403 — no known actor to attribute it to.
            - **Outcome lives in `detail`, not a new column.** `entry_hash()` hashes `detail`, so
              the outcome is tamper-evident for free; a column would sit outside the hash unless
              `entry_hash` changed, and changing it would invalidate verification of every entry
              already written. No migration, and an absent `_outcome` reads as success, so nothing
              needed backfilling.
            - **The domain action name is kept.** A denied role change is `user.role_changed` with
              `detail._outcome="denied"` + `_denial_code`, never `user.role_changed.denied` — so
              "everything Budi did" stays one query. The one exception is `access.forbidden`
              (`require_role`), where the handler never runs so there is no domain action to name.
            - **Denials commit in their OWN transaction.** A request runs in one transaction
              (`_tenant_scoped_session`); the guard's `HTTPException` rolls it back, taking any
              audit row on that session with it. `record_denial` therefore takes no session at all.
              `tests/test_audit_denials_pg.py` proves it against real Postgres with a control row
              that must vanish while the denial survives.
            - **Chained under the ACTOR's agency**, the reverse of the success path: nothing
              happened to the target, and an outsider's rejected attempt must not be appendable to
              another tenant's chain.
            - **Capped** at 5 per (agency, actor, action) per 5 min, in-process — so the effective
              cap is 5 × workers. The last recorded entry carries `_denial_cap_reached` and the
              `/audit` UI surfaces it, so a capped chain can't be mistaken for a quiet one.
            - Wired: the five UAM guards (`privilege_escalation`, `self_lockout`, `last_admin`,
              `cross_agency_forbidden`, `user_not_found`) and `require_role` — which covers the
              admin API and dispatch in one place. `user_not_found` IS recorded: under RLS a
              cross-agency target surfaces as 404, so a run of them is id enumeration; the entry
              names only the id the caller supplied and is never enriched, so it leaks nothing.
            - UI: `/audit` renders a denial with a DENIED chip, red treatment and *tried to*
              phrasing plus the reason. A refused platform-admin grant that rendered like a
              successful one would be worse than not recording it.
      - [ ] **Decide** whether `uncover.custody` should collapse into the core trail. They are NOT
            duplicates: custody is per-process/in-memory and only fills `ActionBundle.audit` in the
            API response (never stored — see `uncover/repository.py`), while `core.audit_log` is the
            durable per-agency trail. Merging changes that API contract, so it is a product decision,
            not a cleanup. Both docstrings now say so.
- [ ] **Two latent defects found while auditing denials** · S each · *surfaced 2026-08-22, neither
      caused by that work* — recorded because both are the quiet kind that surface as something else.
      - [x] **`core.audit_log.seq` allocation race** · **DONE (2026-08-22)** — it was worse than
            duplicate numbering: `seq` AND `prev_sha256` both come from the same chain-head read, so
            concurrent writers produced entries claiming the same position *and* the same
            predecessor. Measured with 8 simultaneous writers on one agency: **all 8 wrote `seq=1`
            with `prev=GENESIS`** — an 8-way fork, reported by `verify_chain` as a broken chain,
            i.e. as *tampering*.
            **`pg_advisory_xact_lock` was tried and rejected — it deadlocks.** The request
            transaction would hold the lock while `record_denial`'s separate transaction waits for
            it on another connection, and the request cannot release it because it is `await`ing
            that very call. Postgres reports **no** deadlock, because the holder is blocked in
            Python, not on a database resource — verified empirically: it hangs indefinitely.
            Shipped instead: **UNIQUE `(agency_id, seq)`** (migration `20260822_17`, NULL `seq`
            still permitted) as the correctness guarantee, plus a **bounded retry** in
            `PostgresAuditRepository.record` that re-reads the head — under a SAVEPOINT, because a
            unique violation aborts the surrounding transaction. Retry budget is what decides
            survival under contention (10 attempts; 5 was measurably too few for 8 writers);
            jittered backoff helps secondarily. Exhaustion drops the entry and logs **ERROR**.
            A unique index has the *same* un-outwaitable wait when the conflicting row is
            uncommitted in the enclosing transaction, so the denial path — the only writer that
            opens a connection inside another open transaction — now sets a short `LOCAL
            lock_timeout`, turning that hang into a fast, loud, logged drop. Pinned by a test.
      - [ ] **A DROPPED audit entry is invisible to `verify_chain`** · S · *surfaced by the fix
            above, not caused by it* — the chain detects a FORK, but an entry that was never
            written leaves no gap in the prev-links, so the log verifies clean and the loss shows
            up only as an ERROR line in the application log. That is the wrong place for it: the
            evidentiary record should be able to say "something is missing" on its own, without
            depending on whether anyone was tailing logs that day. Needs a separate mechanism — a
            per-agency write-attempt counter reconciled against `max(seq)`, or alerting on that
            ERROR. Exhaustion now requires sustained contention rather than a transient blip, so
            this is a real but narrow hole; it belongs with metrics/alerting work.
      - [ ] **`get_mode_resolver()` caches the `Settings` INSTANCE.** It is `@lru_cache`d, so
            `get_settings.cache_clear()` does not reach it and the resolver keeps pointing at an
            orphaned `Settings` while tests mutate the new singleton. Today the pgserver tests pass
            only because they sort alphabetically AFTER the auth tests; a new test file that sorts
            earlier breaks three auth tests, which is exactly what happened here (worked around
            locally in that file's fixture). **The trap stays armed for the next early-sorting
            file.** Real fix: `ModeResolver` should read settings at use, not capture them.
- [x] **`alembic check` drift reconciliation** · S–M · **DONE (2026-08-16)** — the last leg of the
      migration guards. All four drift items were the same shape (the DB had the object, the ORM model
      never declared it), so they were reconciled model-side with **no schema change and no migration**:
      casedata index/FK declarations, `wallet_risk_scores.wallet_id` nullability, and the `messages`
      unique constraint. `alembic check` now runs in CI (`test_models_match_migrations`, against the
      ephemeral pgserver cluster — no external DB), catching the direction the other guards can't: a
      model edited with no migration written, which is exactly how the `stage` outage was authored.
      **Verified the guard actually fails** by injecting an undeclared column and watching it go red.
      Caveat recorded in the test: autogenerate doesn't diff CHECK constraints, RLS policies, or
      server-side functions, so green means "no detectable table/column/index/constraint drift".
- [ ] **Qwen TTS provider** · S · *researched & skipped 2026-08-16, optional* — only the **hosted
      Qwen-Audio-3.0-TTS-Flash** (DashScope) has Indonesian; the open-source Qwen3-TTS does not. Cheap
      (~$0.013/1K chars) + expressive/voice-cloning, but "free" is a **90-day trial**, not ongoing (Google
      TTS stays free monthly), needs a new **Alibaba DashScope key**, and Alibaba Cloud is a data-governance
      flag for LIVE forensics. Doesn't fill a gap (Google/Gemini/ElevenLabs already wired). Wire as a
      flip-to-LIVE adapter (`ITTU_QWEN_API_KEY`) only if its voices are wanted.
- ❌ **AI Rudder — evaluated & REJECTED (2026-08-16)** — enterprise AI voice-agent platform (BotLab,
      no-code), 500+ clients, strong Indonesia/SEA footprint; built for loan collection, telemarketing,
      KYC. **Rejected on architecture, not price: it owns the conversation**, so ITTU's persona loop,
      entity extraction and SHA-256 hash-chained custody are all bypassed — you get transcripts
      secondhand (no public API/webhook docs; enterprise sales only) and nothing court-usable out the
      other end. That objection does **not** dissolve at scale — 1,000 concurrent calls have the same
      problem as one, so there is no "use it later when we're bigger" path for the honeypot. It could
      only ever fit a *different, non-forensic* workload (e.g. mass victim outreach/warning campaigns,
      which need no evidence chain) — a separate product, not ITTU. Also: no self-serve (can't
      prototype), opaque custom pricing, and a commercial third party processing + storing scam-call
      content is a data-governance flag for law-enforcement evidence. **Keep as market context only**
      (proof Indonesian voice AI works commercially — worth a capstone mention). Stay with Twilio as
      dumb transport + our own STT/TTS/agent loop: the custody chain IS the product.
- [ ] **Voice honeypot — outbound calling MVP** · L · *phases 1-4+6 SHIPPED; only phase 5 (Twilio) left* — full architecture in
      [`Voice-Honeypot-Outbound.md`](Voice-Honeypot-Outbound.md): a number pool, a bulk-upload dial
      campaign (Dramatiq-paced, mirrors the C1 notification worker), and a triage queue that attaches
      each connected call's session to a matched case or leaves it for an investigator to assign.
      - [x] **Phase 1 — data model** (`e69f938`) — `honeypot` schema (numbers, dial_campaigns,
            dial_targets) + call columns on `intel.scam_sessions`, RLS on all three (dial_targets policed
            via a join through its campaign).
      - [x] **Phase 2 — case "Calls & conversations" list** (`b82726f`) — see the separate entry below.
      - [x] **Phase 3 — Numbers + Campaigns CRUD + Honeypot Ops UI** (`7e4e9c8`) — `/api/honeypot/*`,
            new `/honeypot-ops` page. Bulk upload reports per-row rejects instead of failing the batch;
            a bare local number (`08…`) is REJECTED, never auto-prefixed to `+62` — guessing a country
            code in a police dialer could call an unrelated real person.
      - [x] **Phase 4 — POC dial worker + Requeue + call log** (`fad427a`, `f27b903`) — paced/retried
            Dramatiq actor, Requeue, and `honeypot.dial_attempts`: EVERY attempt logged, not just
            connected calls, so "tried 3 times, never answered" survives.
      - [ ] **Phase 5 — real Twilio `PstnChannelAdapter` + media bridge** — `Live-Voice-Calls.md`'s
            scope; needs a Twilio account. Self-test/demo numbers only (see Gated below for real targets).
      - [x] **Phase 6 — triage queue + case-linking** (`fdb3b3f`) — exact-match linking only; the
            dialer runs as the owning role so RLS does NOT filter it, and the agency check there is
            load-bearing (asserted by test).
- [x] **Case detail: "Calls / Conversations" list** · S · **DONE (2026-08-16, `b82726f`)** — session rows
      on the case are now expandable into the existing transcript view, with `started_at` shown and voice
      calls badged. Deliberately no mock fallback on that fetch: a mock transcript rendered under a real
      case would be misleading evidence. Duration/recording/disposition columns arrive with phase 4/5.

## 🔒 Gated — blocked on external approval (start the conversations now, don't build yet)
- [ ] **A2 — Telegram channel** · M · **Polri** authorization
- [ ] **B2 + B3 — STT (Whisper streaming) + Twilio telephony** · L · **Polri** — the
      `PstnChannelAdapter` + media bridge (`Live-Voice-Calls.md`); dialing *real reported scam numbers*
      via the outbound campaign feature (`Voice-Honeypot-Outbound.md`) is the same gate — self-test/demo
      numbers are exempt (you're calling yourself), real targets are not.
- [ ] **A3 — Address tags feed** (OFAC/Arkham/chainabuse) · M · **partner**
- [ ] **C2 — Fiat feed** · L · **PPATK / bank** partnership
- [ ] **F3 — Identity hardening** (Keycloak IdP + delegated admin + cross-agency sharing) · L ·
      real multi-agency deployment

## 📜 Non-code long-pole — legal/institutional (start early, they're the slow ones)
- [ ] Polri law-enforcement authorization (any live suspect engagement)
- [ ] PPATK / bank partnership (live fiat feed)
- [ ] Data-protection & evidence-admissibility compliance
