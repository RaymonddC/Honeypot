"""Notification hub — routing table + POC mock sink (nothing leaves)."""

import pytest

from app.core.adapters import get_adapter, registered
from app.uncover.documents import AccountTarget, WalletTarget
from app.uncover.notifications import (
    MockNotificationSink,
    NotificationSink,
    route_targets,
)

WALLETS = [WalletTarget(address="TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6")]
ACCOUNTS = [
    AccountTarget(account_number="111", bank_name="BCA", role="mule"),
    AccountTarget(account_number="222", bank_name="BCA", role="mule"),
    AccountTarget(account_number="333", bank_name="BSI", role="collector_mule"),
]
ALL_OUTPUTS = ["freeze", "ltkm", "alert", "pack"]


def test_routing_full_bundle_investment():
    plan = route_targets("investment", ACCOUNTS, WALLETS, ALL_OUTPUTS)
    agencies = {t.agency for t in plan}
    # one freeze per holding bank (BCA grouped), exchange, PPATK STR, OJK+Polri alerts
    assert "Bank BCA" in agencies and "Bank BSI" in agencies
    assert "Exchange (Indodax)" in agencies
    assert "PPATK" in agencies
    assert "OJK" in agencies
    assert any("Polri" in a for a in agencies)

    bca = next(t for t in plan if t.agency == "Bank BCA")
    assert bca.agency_type == "bank"
    assert bca.channel == "iasc"
    assert bca.document_type == "account_blocking"
    assert "111" in bca.reason and "222" in bca.reason

    ppatk = next(t for t in plan if t.agency == "PPATK")
    assert ppatk.channel == "goaml"
    assert ppatk.document_type == "str_report"


def test_routing_gated_by_outputs():
    # No freeze output → no bank/exchange targets
    plan = route_targets("investment", ACCOUNTS, WALLETS, ["ltkm"])
    assert {t.agency for t in plan} == {"PPATK"}
    # No ltkm → no PPATK
    plan = route_targets("investment", ACCOUNTS, WALLETS, ["freeze"])
    assert all(t.document_type == "account_blocking" for t in plan)
    # judol alerts route to Polri, not OJK
    plan = route_targets("judol_deposit", [], [], ["alert"])
    assert [t.agency_type for t in plan] == ["police"]


def test_routing_wallet_only_freeze_targets_exchange_not_banks():
    plan = route_targets("investment", [], WALLETS, ["freeze"])
    assert [t.agency for t in plan] == ["Exchange (Indodax)"]
    assert plan[0].agency_type == "exchange"


def test_notification_adapters_registered_poc_and_live():
    reg = registered()
    assert reg[("notification", "poc")] == "MockNotificationSink"
    assert reg[("notification", "live")] == "LiveNotificationSink"
    sink = get_adapter("notification", "uncover")  # uncover defaults to POC
    assert isinstance(sink, NotificationSink)
    assert sink.data_mode == "poc"


async def test_mock_sink_records_status_mock_and_nothing_leaves():
    MockNotificationSink.reset()
    sink = MockNotificationSink()
    note = await sink.dispatch({
        "action_id": "act_1", "case_id": "CASE-1", "agency": "PPATK",
        "agency_type": "regulator", "channel": "goaml",
        "document_ids": ["doc_1"], "document_hashes": ["ff" * 32],
    })
    assert note.status == "mock"
    assert note.data_mode == "poc"
    assert note.sent_at is not None
    assert note.target_agency == "PPATK"
    assert "would dispatch to PPATK" in note.payload["note"]
    assert note.payload["document_hashes"] == ["ff" * 32]
    # recorded in the in-process mock ledger — the only place it "went"
    assert MockNotificationSink.sent[-1].id == note.id
    MockNotificationSink.reset()


async def test_live_sink_fails_loudly():
    from app.core.config import get_settings
    from app.uncover.notifications import LiveNotificationSink

    sink = LiveNotificationSink(get_settings())
    with pytest.raises(NotImplementedError):
        await sink.dispatch({"agency": "PPATK"})
