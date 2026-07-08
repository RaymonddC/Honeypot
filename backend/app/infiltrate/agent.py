"""Conversation Orchestrator — the thin agent loop (docs/INFILTRATE-Design.md §3).

A few hundred lines we own, calling a provider-agnostic ``LLMGateway``. Per
inbound scammer turn it: loads the persona system prompt + running state →
calls the gateway with the covert tool specs → dispatches the returned tool
calls (silent side-effects) → sends the persona reply back over the channel.
Both directions are captured as ordered turns for custody + extraction
downstream (service.py hashes them into the message chain).

The covert tools (OLAF ``flag_emotional_distress`` pattern) are side-effect
only and can NEVER send money/PII or touch external systems (legal gate):
- ``record_entity(type, value, context, …)`` — a Layer-B (LLM) entity hint,
  later reconciled against the deterministic Layer-A regex validators.
- ``flag_scam_signal(signal, detail)`` — mark a scam indicator (feeds classifier).
- ``escalate_to_analyst(reason, detail)`` — human-in-the-loop at high-value turns.
"""

from pydantic import BaseModel, Field

from app.infiltrate.channels import ChannelAdapter, ChannelMessage
from app.infiltrate.gateway import LLMGateway, ToolCall
from app.infiltrate.personas import Persona

# Covert tool specs advertised to the gateway (LiteLLM/OpenAI tool schema shape).
COVERT_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "record_entity",
            "description": "Silently record an entity the scammer volunteered "
            "(bank account, crypto wallet, phone, url). Never sends anything.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string",
                             "enum": ["bank_account", "crypto_wallet", "phone", "url"]},
                    "value": {"type": "string"},
                    "chain": {"type": "string"},
                    "bank_name": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["type", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "flag_scam_signal",
            "description": "Flag a scam indicator observed in the conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "signal": {"type": "string"},
                    "detail": {"type": "string"},
                },
                "required": ["signal"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_analyst",
            "description": "Escalate to a human analyst at a high-value or bot-probe turn.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                    "detail": {"type": "string"},
                },
                "required": ["reason"],
            },
        },
    },
]


class TurnRecord(BaseModel):
    """One full exchange: inbound scammer message + outbound persona reply."""

    turn: int
    inbound: ChannelMessage
    outbound: ChannelMessage
    tool_calls: list[ToolCall] = Field(default_factory=list)


class AgentRun(BaseModel):
    """Result of a full replay: ordered turns + collected covert side-effects."""

    persona_id: str
    channel: str
    channel_ref: str
    data_mode: str
    turns: list[TurnRecord] = Field(default_factory=list)
    entity_hints: list[dict] = Field(default_factory=list)   # from record_entity
    scam_signals: list[dict] = Field(default_factory=list)   # from flag_scam_signal
    escalations: list[dict] = Field(default_factory=list)    # from escalate_to_analyst

    @property
    def escalated(self) -> bool:
        return bool(self.escalations)


async def run_session(
    persona: Persona,
    channel: ChannelAdapter,
    gateway: LLMGateway,
    max_turns: int = 50,
) -> AgentRun:
    """Drive the conversation to completion (channel exhausts) or ``max_turns``.

    Transport-agnostic: works over the POC replay adapter or any LIVE channel.
    """
    run = AgentRun(
        persona_id=persona.id,
        channel=getattr(channel, "channel", "unknown"),
        channel_ref=getattr(channel, "channel_ref", ""),
        data_mode=getattr(gateway, "data_mode", "poc"),
    )

    # System prompt anchors every completion (persona + reactive guardrails).
    conversation: list[dict] = [{"role": "system", "content": persona.system_prompt()}]

    turn = 0
    while turn < max_turns:
        inbound = await channel.receive()
        if inbound is None:
            break  # scammer conversation ended
        conversation.append({"role": "user", "content": inbound.content})

        resp = await gateway.complete(conversation, tools=COVERT_TOOLS, turn=turn)

        # Dispatch covert side-effect tools (silent to the scammer).
        _dispatch_tools(run, resp.tool_calls, turn)

        outbound = await channel.send(
            resp.content,
            meta={
                "turn": turn + 1,
                "model": resp.model,
                "tool_calls": [tc.model_dump() for tc in resp.tool_calls],
            },
        )
        conversation.append({"role": "assistant", "content": resp.content})

        run.turns.append(
            TurnRecord(turn=turn, inbound=inbound, outbound=outbound, tool_calls=resp.tool_calls)
        )
        turn += 1

    return run


def _dispatch_tools(run: AgentRun, tool_calls: list[ToolCall], turn: int) -> None:
    """Execute covert tools — pure side-effects into the run's structured record.

    No tool can send money/PII or reach an external system (enforced here by
    simply having no such capability — the only effect is recording intel).
    """
    for tc in tool_calls:
        args = dict(tc.args)
        args["turn"] = turn
        if tc.name == "record_entity":
            run.entity_hints.append(args)
        elif tc.name == "flag_scam_signal":
            run.scam_signals.append(args)
        elif tc.name == "escalate_to_analyst":
            run.escalations.append(args)
        # Unknown tools are ignored (never granted external capability).
