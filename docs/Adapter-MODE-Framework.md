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

```python
class ModeSettings(BaseSettings):
    mode: Literal["poc", "live"] = "poc"                 # global default (safe)
    module_modes: dict[str, Literal["poc","live"]] = {}  # per-module override
    # e.g. ITTU_MODULE_MODES='{"takedown":"live","infiltrate":"poc"}'

class ProviderSettings(BaseSettings):
    blockchain_provider: str = "tronscan"     # tronscan|trongrid|bitquery
    llm_gateway_url: str                       # self-hosted LiteLLM endpoint
    stt_provider: str = "whisper"
    tts_provider: str = "google"
    # credentials pulled from env / secrets, never in code
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
- Produced rows carry `data_mode`; repositories filter by the request's active mode.
- **LIVE evidence views never read POC rows.** In production, **separate DB instances** per mode
  (distinct creds) so demo data physically cannot enter a real case. (See `docs/Data-Model.md`.)

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
