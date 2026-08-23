# ITTU — Adapter / MODE Framework (deep-dive)

> The backbone of the POC↔LIVE toggle. Every external dependency sits behind an **adapter interface**;
> a **MODE** switch (global default + per-module override) selects the POC or LIVE implementation at
> startup. Same code paths, swapped data sources — so the hackathon POC flips toward production without
> a rewrite. Every module doc references this. Ports-and-adapters (hexagonal) architecture.

---

## Principles
1. **One interface, two implementations.** Each boundary has a `Protocol`/ABC; POC and LIVE classes
   implement it with **identical signatures + identical Pydantic return schemas**. Nothing downstream
   knows which is active.
2. **MODE is config, resolved per module.** Global `ITTU_MODE` default + per-module overrides — e.g.
   TAKEDOWN can run LIVE (real TRON) while INFILTRATE stays POC (replayed transcripts).
3. **POC is the safe default.** LIVE requires explicit config **and** credentials; missing creds fail
   closed to POC (or error), never silently reach out.
4. **Adapters stamp `data_mode`.** POC adapters tag rows `poc`, LIVE tag `live` → the data-model's
   evidentiary isolation (LIVE views never read POC rows; separate DB instances in prod).
5. **Deterministic POC where possible** — repeatable demos + double as test fixtures.

---

## The boundaries

| Boundary | Interface (method) | POC impl | LIVE impl |
|---|---|---|---|
| **LLM** | `LLMGateway.complete()/.stream()` | LiteLLM→free/OpenRouter, or a deterministic stub | LiteLLM→Anthropic/Gemini/**Jatevo** (tiered routing) |
| **Channel (text)** | `ChannelAdapter.receive()/.send()` | replay scam transcripts | Telegram / WhatsApp |
| **Channel (voice)** | `ChannelAdapter` (+ audio) | replay call audio / TTS-scripted caller | PSTN / WA call bridge |
| **STT** | `STTAdapter.transcribe(audio)` | canned transcript | Whisper / Google / Deepgram (Indonesian) |
| **TTS** | `TTSAdapter.synthesize(text)` | pre-rendered audio | ElevenLabs / Google (Bahasa voice) |
| **Blockchain** | `ChainDataAdapter.fetch_transfers()/.balance()` | cached TRON fixtures (Gary's 15–20 addrs) | TRONSCAN / TronGrid / Bitquery |
| **Fiat** | `FiatDataAdapter.load_transactions()` | synthetic PT A2Z generator / PaySim | bank + QRIS feed (post-MoU) |
| **Notification** | `NotificationSink.dispatch(packet)` | mock sink (logged, status=`mock`) | multi-agency dispatch + goAML + IASC |
| **Address tags** | `TagSource.lookup(addr)` | seed file (OFAC/Arkham/chainabuse snapshot) | live tag feeds |

Every module's external touchpoints map to exactly one of these — no ad-hoc HTTP calls outside an adapter.

---

## Config shape (pydantic-settings)

Single `Settings` class (`backend/app/core/config.py`), env-prefixed `ITTU_`:

```python
class Settings(BaseSettings):
    mode: Literal["poc", "live"] = "poc"                  # global default (safe)
    module_modes: dict[str, Literal["poc","live"]] = {}   # per-module override
    # e.g. ITTU_MODULE_MODES='{"takedown":"live","infiltrate":"poc"}'

    # provider credentials/selection — pulled from env, never in code:
    tronscan_api_key: str = ""                            # TRONSCAN (LIVE blockchain)
    llm_model / llm_api_key / llm_api_base                # LLM gateway
    tts_provider: str = "browser"                         # browser (POC) | google|elevenlabs (LIVE)
    google_client_id: str = ""                            # LIVE Google OAuth audience
    oauth_provision: str = ""                             # email→agency/role allowlist (JSON)
```

```
ITTU_MODE=poc                    # global default
ITTU_MODULE_MODES={"takedown":"live"}
BLOCKCHAIN_PROVIDER=tronscan
LLM_GATEWAY_URL=http://litellm:4000
```

A `ModeResolver.effective_mode(module: str) -> "poc"|"live"` returns the module override or the global
default.

---

## Registry + factory (resolved at FastAPI `lifespan` startup)

```python
class ChainDataAdapter(Protocol):
    async def fetch_transfers(self, address: str, cursor: str | None = None) -> TransferPage: ...
    async def balance(self, address: str) -> WalletBalance: ...

_REGISTRY: dict[tuple[str, str], type] = {}          # (boundary, mode) -> impl

def register(boundary: str, mode: str):
    def deco(cls): _REGISTRY[(boundary, mode)] = cls; return cls
    return deco

@register("blockchain", "poc")
class CachedTronAdapter:  ...        # reads fixtures; stamps data_mode="poc"

@register("blockchain", "live")
class TronscanAdapter:  ...          # TRONSCAN + Redis cache + rate-limit; data_mode="live"

def get_chain_adapter(module: str) -> ChainDataAdapter:
    mode = mode_resolver.effective_mode(module)
    return _REGISTRY[("blockchain", mode)](settings)   # DI'd via FastAPI Depends
```

- Interfaces returned via **FastAPI dependencies** (`Depends(get_chain_adapter)`), so routers/services
  never construct adapters directly.
- Adapters are **async** (I/O-bound); CPU-bound work (ML/graph) stays off the event loop (Dramatiq).

---

## Interface contract rules
- **Identical signatures + Pydantic return models** across POC/LIVE — enforced by **contract tests**
  that run the same suite against both implementations.
- LIVE adapters own **rate-limiting, retries, caching** (Redis) internally or via a shared decorator.
- POC adapters are **deterministic** and offline (no network) → safe demos + CI.
- Each adapter exposes `data_mode` and stamps produced rows accordingly.

---

## `data_mode` enforcement (evidentiary integrity)

> **BUILT 2026-08-23 (migration `20260823_18`) — as ROW-LEVEL SECURITY, not separate databases.**
> The earlier text here described separate DB instances per mode; that is not what shipped, and
> the difference matters. Mode is now a per-transaction RLS predicate, the same mechanism that
> already enforces tenant isolation. Two named exceptions are listed below — they are deliberate,
> not gaps waiting to be filled.

**How it works.** `_tenant_scoped_session` sets `app.data_mode` alongside `app.current_agency`;
`core.current_mode()` reads it; every agency-scoped policy compares it to the row's `data_mode`.
A query that forgets to filter *cannot* leak, because the database refuses — rather than every
future query having to remember.

- **Fail-closed.** `current_setting(..., true)` is NULL when unset and `data_mode = NULL` is never
  true, so a session that never sets the variable sees nothing. A garbage value also sees nothing.
  Verified against a real Postgres, not assumed (`test_mode_isolation_pg.py`).
- **The write side is guarded too.** Postgres applies `USING` as the implicit `WITH CHECK` for
  INSERT, so a mode-mismatched write is REFUSED rather than written-and-hidden. That behaviour is
  load-bearing and is pinned by a test: an explicit permissive `WITH CHECK` on a future policy
  would silently remove it.
- **19 tables** carry the predicate. `intel.syndicate_members` has no `data_mode` of its own and
  inherits its parent syndicate's.

**Exception 1 — `core.audit_log` is deliberately NOT mode-filtered.** `verify_chain` walks every
entry's `prev_sha256` in `seq` order, so hiding any entry breaks the chain: a LIVE session would
see a FALSE TAMPER ALARM, and a POC session would see SILENT TRUNCATION (the trail verifies clean
while records are missing — the exact gap `ittu_audit_entries_dropped_total` exists to close). It
is also arguably wrong on the merits: the trail answers "everything that happened in this tenant",
and the POC→LIVE transition is the most interesting entry in it. Mode is recorded as
`detail['_data_mode']` — inside `entry_hash`, so tamper-evident, and still filterable via
`detail->>'_data_mode'`. Provenance belongs *in* the record; it does not decide who may read it.

**Exception 2 — background workers bypass this entirely.** A Dramatiq actor connects as the
OWNING role (`worker_session`), which bypasses RLS by design, so actor code must check `data_mode`
explicitly exactly as it must scope by `agency_id`. Both actors refuse a mismatched row.

**Not applicable — `chain.*` / `fiat.*` raw ledger tables.** Deliberately not agency-scoped
(public-ledger reference facts), and as of this migration they have zero read sites and zero write
sites — the data flows through adapters, never through Postgres. Whoever first persists them must
add a mode-only policy then; recorded in `docs/Data-Model.md`.

**Config constraint this introduces:** under `ITTU_PERSISTENCE=postgres`, per-module modes that
disagree with the global `ITTU_MODE` are **refused at boot**. `app.data_mode` is one value per
transaction and a request spans modules, so a per-module mode cannot be honestly stamped on a row.
Mixed module modes remain fully supported under `ITTU_PERSISTENCE=memory`.

## Mode granularity (MVP decision)
- **Module-level, deployment-resolved** for the MVP (simple, predictable).
- Per-case `data_mode` tagging still isolates demo vs real data within a deployment.
- (Per-request/per-case *mode switching* is a later refinement if needed.)

---

## Reuse & build
| Piece | Source | Action |
|---|---|---|
| pydantic-settings config pattern, app-factory + lifespan | OLAF | **Reuse** |
| Rate-limited service-client pattern (blockchain) | ELSA | **Reuse** (port) |
| LLM gateway (LiteLLM) as the LLM boundary impl | new (self-hosted) | **Build/deploy** |
| Registry/factory + ModeResolver + contract-test harness | — | **Build** (Phase 0) |

## Open questions
1. **Secrets management** — env/Docker secrets for MVP; Vault/SM for LIVE/on-prem.
2. **Partial-LIVE guards** — warn loudly when a module is LIVE but a dependency (e.g. bank feed) is
   unavailable, rather than silently degrading.
3. **Contract-test coverage** — ensure every boundary has POC+LIVE parity tests before LIVE rollout.
