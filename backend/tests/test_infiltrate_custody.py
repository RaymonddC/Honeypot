"""Chain-of-custody — SHA-256 hash-chain over honeypot messages + tamper detection."""

from datetime import datetime, timezone

from app.infiltrate.custody import GENESIS, MessageChain
from app.infiltrate.channels import REPLAY_SCRIPT

TS = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)


def _build_chain() -> MessageChain:
    chain = MessageChain("sess_custody")
    for turn in REPLAY_SCRIPT:
        chain.append("inbound", turn.scammer, TS)
        chain.append("outbound", turn.persona_reply, TS)
    return chain


def test_chain_is_ordered_and_linked():
    chain = _build_chain()
    msgs = chain.messages()
    assert len(msgs) == len(REPLAY_SCRIPT) * 2
    assert msgs[0].prev_sha256 == GENESIS
    # Each link points at the previous hash.
    for prev, cur in zip(msgs, msgs[1:]):
        assert cur.prev_sha256 == prev.sha256
        assert cur.seq == prev.seq + 1


def test_untampered_chain_verifies():
    assert _build_chain().verify() is True


def test_content_tamper_is_detected():
    chain = _build_chain()
    chain._messages[3].content = "5271038462 → 9999999999"  # forge an account number
    assert chain.verify() is False


def test_reorder_tamper_is_detected():
    chain = _build_chain()
    chain._messages[2], chain._messages[4] = chain._messages[4], chain._messages[2]
    assert chain.verify() is False


def test_head_matches_last_hash():
    chain = _build_chain()
    assert chain.head == chain.messages()[-1].sha256


def test_hash_is_deterministic():
    a, b = _build_chain(), _build_chain()
    assert [m.sha256 for m in a.messages()] == [m.sha256 for m in b.messages()]
