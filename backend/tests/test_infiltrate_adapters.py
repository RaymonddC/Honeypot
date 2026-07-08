"""INFILTRATE adapters — POC replay + scripted gateway determinism, LIVE fail-loud."""

import pytest

from app.core.adapters import get_adapter
from app.infiltrate.agent import run_session
from app.infiltrate.channels import REPLAY_SCRIPT, TelegramChannelAdapter
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


def test_poc_is_the_registered_default():
    # INFILTRATE stays POC by default — never silently resolves LIVE.
    channel = get_adapter("channel", "infiltrate")
    gateway = get_adapter("llm", "infiltrate")
    assert channel.data_mode == "poc"
    assert gateway.data_mode == "poc"
