"""The seam between a call and everything downstream.

Placing a triaged call used to set ``session.case_id`` and nothing else. The
account a scammer read out stayed on ``intel.entities``, attached to the
SESSION — while TRACE's watchlist, the case view and UNCOVER's freeze request
all read ``casedata.bank_accounts``. So a real call produced a real entity and
an empty case, and the golden thread broke exactly here.
"""

import pytest

from app.casedata.repository import InMemoryCaseDataRepository
from app.honeypot_ops.triage import copy_entities_to_case
from app.infiltrate.service import EntityOut


class _Entities:
    """Minimal stand-in for the infiltrate repo — only list_entities is used."""

    def __init__(self, entities):
        self._entities = entities

    async def list_entities(self, session_id=None, status=None):
        return self._entities


def _entity(**kw):
    from datetime import datetime, timezone

    base = dict(
        id="ent_1", session_id="sess_1", message_id="msg_1",
        type="bank_account", value="5271038462", normalized_value="5271038462",
        method="regex", confidence=0.9, review_status="unverified",
        created_at=datetime.now(timezone.utc),
    )
    base.update(kw)
    return EntityOut(**base)


@pytest.mark.anyio
async def test_a_disclosed_account_becomes_a_tracked_account_on_the_case():
    cd = InMemoryCaseDataRepository()
    n = await copy_entities_to_case(
        "sess_1", "case_1",
        infiltrate_repo=_Entities([_entity(bank_name="BCA")]),
        casedata_repo=cd,
    )
    assert n == 1
    tracked = await cd.list_bank_accounts("case_1")
    assert [a.account_number for a in tracked] == ["5271038462"]
    assert tracked[0].bank_name == "BCA"
    # An account a scammer gives out to receive a transfer IS a receiving
    # account — the same literal the rest of the demo data uses.
    assert tracked[0].category == "mule"


@pytest.mark.anyio
async def test_the_note_carries_provenance_and_how_certain_we_are():
    """A case that cannot show which accounts a human has confirmed invites
    someone to freeze the wrong one. Extractions arrive unverified."""
    cd = InMemoryCaseDataRepository()
    await copy_entities_to_case(
        "sess_1", "case_1",
        infiltrate_repo=_Entities([_entity(bank_name="BCA", confidence=0.8)]),
        casedata_repo=cd,
    )
    note = (await cd.list_bank_accounts("case_1"))[0].note
    assert "sess_1" in note                 # which call disclosed it
    assert "regex" in note                  # how it was extracted
    assert "0.80" in note                   # how confident that was
    assert "unverified" in note             # and that nobody has confirmed it


@pytest.mark.anyio
async def test_copying_twice_does_not_duplicate_the_account():
    """Two calls can disclose the same account, and a call can be re-attached."""
    cd = InMemoryCaseDataRepository()
    repo = _Entities([_entity(bank_name="BCA")])
    assert await copy_entities_to_case("sess_1", "c1", infiltrate_repo=repo, casedata_repo=cd) == 1
    assert await copy_entities_to_case("sess_1", "c1", infiltrate_repo=repo, casedata_repo=cd) == 0
    assert len(await cd.list_bank_accounts("c1")) == 1


@pytest.mark.anyio
async def test_wallets_are_not_copied_because_casedata_stores_transfers():
    """A disclosed address is a NODE; casedata holds edges (from -> to, value,
    time). Writing one would mean inventing a transaction nobody observed."""
    cd = InMemoryCaseDataRepository()
    wallet = _entity(type="crypto_wallet", value="TLaJLQ1Aiqu8YpZLNG37vDCrFxiFL3JWmn",
                     normalized_value="TLaJLQ1Aiqu8YpZLNG37vDCrFxiFL3JWmn")
    n = await copy_entities_to_case(
        "sess_1", "c1", infiltrate_repo=_Entities([wallet]), casedata_repo=cd
    )
    assert n == 0
    assert await cd.list_bank_accounts("c1") == []


@pytest.mark.anyio
async def test_a_call_that_extracted_nothing_places_cleanly():
    cd = InMemoryCaseDataRepository()
    assert await copy_entities_to_case(
        "sess_1", "c1", infiltrate_repo=_Entities([]), casedata_repo=cd
    ) == 0


def test_a_tracked_account_reaches_the_freeze_request_pdf():
    """The far end of the thread: what lands on the case is what an officer
    sends to a bank."""
    import re
    import zlib
    from datetime import datetime, timezone

    from app.uncover import documents as docs

    ctx = docs.DocumentContext(
        case_id="c1", crime_type="investment_scam",
        generated_at=datetime.now(timezone.utc),
        accounts=[docs.AccountTarget(
            account_number="5271038462", bank_name="BCA",
            holder_name="Rudi Hartono", role="mule",
        )],
        narrative="Account disclosed on a honeypot voice call.",
    )
    pdf = docs.generate_freeze_request(ctx).pdf
    assert pdf[:5] == b"%PDF-"

    # reportlab compresses its content streams, so read the text back out.
    text = b""
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        try:
            text += zlib.decompress(m.group(1))
        except zlib.error:
            text += m.group(1)
    assert b"5271038462" in text or b"5271038462" in pdf
    assert b"BCA" in text or b"BCA" in pdf
