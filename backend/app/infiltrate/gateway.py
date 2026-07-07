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

LIVE (``LiteLLMGateway``): clean stub — fails loudly. Real impl points at the
self-hosted LiteLLM endpoint with tiered routing (Claude for the
disclosure-critical turns, cheap tier for rapport) once credentials exist.
"""

from typing import Protocol

from pydantic import BaseModel, Field

from app.core.adapters import register
from app.core.config import Mode, Settings
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


@register("llm", "live")
class LiteLLMGateway:
    """LIVE stub — self-hosted LiteLLM gateway with tiered routing.

    Fails loudly: requires ``ITTU_LLM_GATEWAY_URL`` + provider credentials and
    the tiered-routing policy (Claude for disclosure-critical turns). Never
    silently degrades to POC.
    """

    data_mode: Mode = "live"
    model_version = "litellm-tiered"

    def __init__(self, settings: Settings | None = None):
        raise NotImplementedError(
            "LIVE LLM gateway is not wired in this build: it requires a self-hosted "
            "LiteLLM endpoint (ITTU_LLM_GATEWAY_URL) + provider credentials + tiered "
            "routing policy. Run INFILTRATE in POC mode (ITTU_MODE=poc)."
        )

    async def complete(
        self, messages: list[dict], tools: list[dict] | None = None, turn: int = 0
    ) -> LLMResponse:  # pragma: no cover - stub
        raise NotImplementedError
