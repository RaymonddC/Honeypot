"""The registry of what is switched off, and what would switch it on.

A decision aid, not an enforcement mechanism — the guards live where they can
refuse a request. What these tests protect is that the registry stays HONEST:
an entry that misstates who can lift a gate is worse than no entry, because
someone will plan around it.
"""

from __future__ import annotations

from app.core.gated import GATED, GATED_BY_KEY, Blocker, blocked_on_others


def test_the_inbound_and_outbound_honeypot_are_not_the_same_permission():
    """The distinction the pivot rests on.

    Inbound is answering our own phone — we are a party to the conversation, and
    no authority grants permission for that. Outbound is contacting someone who
    has not contacted us. Collapsing the two is what makes the whole product
    look like it needs Polri before it can do anything at all.
    """
    inbound = GATED_BY_KEY["honeypot_inbound"]
    outbound = GATED_BY_KEY["honeypot_outbound"]

    assert inbound.blocker is Blocker.CREDENTIAL, (
        "inbound was marked as needing an authorisation — it needs a phone number"
    )
    assert outbound.blocker is Blocker.POLRI
    assert inbound not in blocked_on_others(), (
        "inbound is listed as blocked on someone else; it is blocked on us"
    )
    assert outbound in blocked_on_others()


def test_crypto_is_blocked_on_us_not_on_anyone_else():
    """A public ledger needs nobody's permission. If this ever moves into the
    externally-blocked list, someone has confused a product decision with a
    constraint — and that is how a capability we control stays off for months."""
    crypto = GATED_BY_KEY["crypto"]
    assert crypto.blocker is Blocker.PRODUCT
    assert crypto not in blocked_on_others()
    assert crypto.flag == "ITTU_CRYPTO_ENABLED"


def test_every_entry_says_who_can_lift_it():
    """"Blocked" without a named party is how something stays blocked forever."""
    for feature in GATED:
        assert feature.lifted_by.strip(), feature.key
        assert len(feature.what) > 60, (
            f"{feature.key}'s description is too thin to decide from"
        )


def test_the_externally_blocked_set_is_the_smaller_one():
    """Sanity on the framing: if MOST capabilities were blocked on outside
    parties, the honest answer would be that the product cannot ship without
    permission. It is the other way round, and that is the point of the split."""
    external = blocked_on_others()
    assert len(external) < len(GATED), (
        "more capabilities are blocked externally than internally — re-check "
        "whether the blockers are recorded accurately"
    )


def test_the_config_endpoint_reports_the_registry():
    import os

    from fastapi.testclient import TestClient

    from app.core.config import Settings, get_settings

    Settings.model_config["env_file"] = None
    os.environ["ITTU_PERSISTENCE"] = "memory"
    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as client:
        gated = client.get("/api/config").json()["gated"]

    assert {g["key"] for g in gated} == {f.key for f in GATED}
    for row in gated:
        assert row["blocker"] and row["lifted_by"]
