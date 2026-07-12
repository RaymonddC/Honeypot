"""LLM boundary — provider-agnostic gateway (LiteLLM-shaped) + POC/LIVE impls.

The Conversation Orchestrator (agent.py) never talks to a provider directly;
it calls ``LLMGateway.complete()`` with a LiteLLM/OpenAI-compatible message
list + tool specs, and gets back a normalized ``LLMResponse`` (reply text +
tool calls). This keeps the loop provider-agnostic — POC swaps in a
deterministic scripted persona, LIVE swaps in a real tiered-routing gateway
(docs/Adapter-MODE-Framework.md: the LLM boundary).

POC (``ScriptedLLMGateway``): **fully offline, no API keys, no network.**
Returns the persona's scripted reply + covert tool calls for the current turn,
driven by ``REPLAY_SCRIPT``. Deterministic → repeatable demos + test fixtures.

LIVE (``LiteLLMGateway``): a REAL model call through litellm (provider-agnostic
OpenAI-compatible client). Paid + opt-in: engages only when INFILTRATE
MODE=live or an interactive session is started, AND ``ITTU_LLM_API_KEY`` (or
``ANTHROPIC_API_KEY``) is present — otherwise it fails loudly at construction.
Default model ``claude-haiku-4-5`` (fast/cheap for live-call latency),
overridable via ``ITTU_LLM_MODEL``.

Keyless interactive fallback (``InteractiveScriptedGateway``): deterministic
in-character stall replies so ``POST /sessions/{id}/turn`` still demos without
any key — Layer-A extraction still runs on whatever the caller said.
"""

import json
from typing import Protocol

from pydantic import BaseModel, Field

from app.core.adapters import register
from app.core.config import Mode, Settings, get_settings
from app.infiltrate.channels import REPLAY_SCRIPT, ScriptTurn


class ToolCall(BaseModel):
    """A covert side-effect tool the model asks the loop to run (silent to scammer)."""

    name: str
    args: dict = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """Normalized gateway response — the persona's reply + any tool calls."""

    content: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    model: str = "poc-scripted-persona-1"


class LLMGateway(Protocol):
    """LLM boundary. POC: deterministic scripted persona; LIVE: LiteLLM tiered routing."""

    data_mode: Mode
    model_version: str

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        turn: int = 0,
    ) -> LLMResponse:
        """One completion. ``turn`` is the 0-based conversation turn index (POC)."""
        ...


@register("llm", "poc")
class ScriptedLLMGateway:
    """POC: returns the scripted persona reply + covert tool calls for ``turn``.

    Offline + deterministic. Ignores the model — the reply for turn *i* is
    ``REPLAY_SCRIPT[i].persona_reply`` with its scripted ``tool_calls``.
    """

    data_mode: Mode = "poc"
    model_version = "poc-scripted-persona-1"

    def __init__(self, settings: Settings | None = None, script: list[ScriptTurn] | None = None):
        self._script = script if script is not None else REPLAY_SCRIPT

    async def complete(
        self, messages: list[dict], tools: list[dict] | None = None, turn: int = 0
    ) -> LLMResponse:
        if turn < 0 or turn >= len(self._script):
            # Out of script — persona goes quiet rather than hallucinate.
            return LLMResponse(content="", model=self.model_version)
        st = self._script[turn]
        return LLMResponse(
            content=st.persona_reply,
            tool_calls=[ToolCall(name=t["name"], args=t.get("args", {})) for t in st.tool_calls],
            model=self.model_version,
        )


# In-character deterministic stalls for the keyless interactive demo. Reactive
# + victim-framed (never initiates, never agrees to send anything) — and the
# hybrid extraction still runs on the caller's words, so speaking a wallet or
# account number at the mic still lands in the entity list.
INTERACTIVE_STALL_LINES: list[str] = [
    "halo? iya ini dengan ibu Sari.. maaf nak, suaranya kurang jelas, ini dari mana ya?",
    "waduh nak, ibu kurang paham soal beginian.. coba jelaskan pelan-pelan ya, "
    "maklum orang tua.",
    "sebentar nak, ibu ambil pulpen dulu ya.. sudah, coba ulangi lagi yang tadi, "
    "biar ibu catat di buku.",
    "hmm begitu ya.. tapi ibu harus tanya anak ibu dulu nak, dia yang paham "
    "urusan uang begini. nomornya atau rekeningnya tadi berapa ya?",
    "aduh maaf nak, telinga ibu sudah kurang.. tolong sebutkan sekali lagi "
    "pelan-pelan, satu-satu ya.",
    "iya iya nak, sabar ya.. nanti sore anak ibu pulang, ibu kabari lagi. "
    "tapi coba ceritakan dulu, ini programnya bagaimana?",
]


class InteractiveScriptedGateway:
    """Keyless fallback persona for interactive ``/turn`` calls (POC-safe).

    Deterministic: turn *i* answers with ``INTERACTIVE_STALL_LINES[i % n]``.
    Never 500s, never needs a key — the graceful-degrade path when INFILTRATE
    is POC / no LLM key is present.
    """

    data_mode: Mode = "poc"
    model_version = "poc-interactive-stall-1"

    def __init__(self, settings: Settings | None = None):
        pass

    async def complete(
        self, messages: list[dict], tools: list[dict] | None = None, turn: int = 0
    ) -> LLMResponse:
        line = INTERACTIVE_STALL_LINES[turn % len(INTERACTIVE_STALL_LINES)]
        return LLMResponse(content=line, model=self.model_version)


async def _litellm_complete(**kwargs):
    """Test seam + lazy import — litellm is heavy and POC never needs it."""
    try:
        from litellm import acompletion
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise RuntimeError(
            "The LIVE LLM gateway needs the `litellm` package (backend dependency). "
            "Install backend deps (`pip install -e .`) or run in POC mode."
        ) from exc
    return await acompletion(**kwargs)


@register("llm", "live")
class LiteLLMGateway:
    """LIVE — one real completion via litellm (OpenAI-compatible, any provider).

    Paid + opt-in. Fails loudly at construction when no key is configured —
    never silently degrades to POC. Model: ``ITTU_LLM_MODEL`` (default
    ``claude-haiku-4-5``); key: ``ITTU_LLM_API_KEY`` (fallback
    ``ANTHROPIC_API_KEY``).
    """

    data_mode: Mode = "live"

    def __init__(self, settings: Settings | None = None):
        settings = settings or get_settings()
        self._model = settings.llm_model
        self.model_version = self._model
        self._api_key = settings.effective_llm_api_key
        self._api_base = settings.llm_api_base or None
        if not self._api_key:
            raise NotImplementedError(
                "LIVE LiteLLM gateway is not usable in this build: no API key is "
                "configured. Set ITTU_LLM_API_KEY (or ANTHROPIC_API_KEY). The live "
                "brain never runs keyless — run INFILTRATE in POC mode "
                "(ITTU_MODE=poc) instead."
            )

    async def complete(
        self, messages: list[dict], tools: list[dict] | None = None, turn: int = 0
    ) -> LLMResponse:
        resp = await _litellm_complete(
            model=self._model,
            messages=messages,
            tools=tools or None,
            api_key=self._api_key,
            api_base=self._api_base,  # None unless ITTU_LLM_API_BASE is set
            max_tokens=1024,
            temperature=0.8,
        )
        message = resp.choices[0].message
        tool_calls: list[ToolCall] = []
        for tc in message.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            if not isinstance(args, dict):
                args = {}
            tool_calls.append(ToolCall(name=tc.function.name, args=args))
        return LLMResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            model=getattr(resp, "model", None) or self._model,
        )
