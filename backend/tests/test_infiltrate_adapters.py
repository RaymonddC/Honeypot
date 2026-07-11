"""INFILTRATE adapters — POC replay + scripted gateway determinism, LIVE fail-loud."""

import json
import types

import pytest

from app.core.adapters import get_adapter
from app.core.config import Settings
from app.infiltrate.agent import run_session
from app.infiltrate.channels import REPLAY_SCRIPT, TelegramChannelAdapter
from app.infiltrate import gateway as gateway_module
from app.infiltrate.gateway import LiteLLMGateway
from app.infiltrate.personas import get_persona


async def test_poc_agent_loop_is_deterministic():
    persona = get_persona(None)
    runs = []
    for _ in range(2):
        run = await run_session(
            persona, get_adapter("channel", "infiltrate"), get_adapter("llm", "infiltrate")
        )
        runs.append(run)
    assert len(runs[0].turns) == len(REPLAY_SCRIPT)
    # Same scripted replies + covert side-effects every run.
    assert [t.outbound.content for t in runs[0].turns] == [t.outbound.content for t in runs[1].turns]
    assert len(runs[0].entity_hints) == len(runs[1].entity_hints) == 5
    assert runs[0].escalated is True


async def test_covert_tools_collected_by_kind():
    run = await run_session(
        get_persona(None), get_adapter("channel", "infiltrate"),
        get_adapter("llm", "infiltrate"),
    )
    hint_types = [h["type"] for h in run.entity_hints]
    assert "crypto_wallet" in hint_types and "bank_account" in hint_types
    assert run.scam_signals and run.escalations


def test_live_channel_adapter_fails_loudly():
    with pytest.raises(NotImplementedError, match="Telegram"):
        TelegramChannelAdapter()


def test_live_llm_gateway_fails_loudly():
    with pytest.raises(NotImplementedError, match="LiteLLM"):
        LiteLLMGateway()


def test_live_llm_gateway_requires_no_key_when_anthropic_env_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(NotImplementedError, match="LiteLLM"):
        LiteLLMGateway(Settings(llm_api_key=""))


def _fake_litellm_response(content: str, tool_calls=None, model="claude-haiku-4-5"):
    """A minimal stand-in for litellm's ModelResponse shape."""
    message = types.SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)], model=model)


def _fake_tool_call(name: str, args: dict):
    return types.SimpleNamespace(
        function=types.SimpleNamespace(name=name, arguments=json.dumps(args))
    )


async def test_live_llm_gateway_completes_with_a_key_hermetically(monkeypatch):
    """Selected with a key configured → does a REAL completion call... but the
    call itself (`_litellm_complete`) is mocked, so this never touches the
    network or needs the `litellm` package installed."""
    calls = []

    async def fake_complete(**kwargs):
        calls.append(kwargs)
        return _fake_litellm_response(
            "baik nak, dicatat ya",
            tool_calls=[_fake_tool_call("record_entity", {"type": "phone", "value": "0812"})],
        )

    monkeypatch.setattr(gateway_module, "_litellm_complete", fake_complete)

    gw = LiteLLMGateway(Settings(llm_api_key="sk-test-not-real", llm_model="claude-haiku-4-5"))
    assert gw.data_mode == "live"
    resp = await gw.complete([{"role": "user", "content": "halo"}], tools=[{"x": 1}], turn=0)

    assert resp.content == "baik nak, dicatat ya"
    assert resp.model == "claude-haiku-4-5"
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "record_entity"
    assert resp.tool_calls[0].args == {"type": "phone", "value": "0812"}
    # The key reached the (mocked) provider call, never a response.
    assert calls[0]["api_key"] == "sk-test-not-real"
    assert calls[0]["model"] == "claude-haiku-4-5"


def test_poc_is_the_registered_default():
    # INFILTRATE stays POC by default — never silently resolves LIVE.
    channel = get_adapter("channel", "infiltrate")
    gateway = get_adapter("llm", "infiltrate")
    assert channel.data_mode == "poc"
    assert gateway.data_mode == "poc"
