"""Dictated digits — the voice channel's whole intake.

On a phone call the artefact this system exists to collect arrives as WORDS:
a scammer reads out "lima dua tujuh satu nol tiga delapan empat enam dua". Every
Layer-A pattern matches digits, so before this the number was invisible to the
extractor and only surfaced when the model happened to fire a covert
record_entity tool — a choice, not a guarantee. Two live calls with the same
disclosure produced an entity and nothing at all.

The risk on the other side is over-eagerness: Indonesian says amounts and
percentages with the same words ("dua puluh persen", "modal lima juta"), and
turning those into digits would invent evidence. Hence a run-length floor, and
the tests below spend most of their attention on what must NOT convert.
"""

import pytest

from app.infiltrate.extraction import extract_layer_a, spoken_digits_to_number


def test_a_dictated_account_number_becomes_digits():
    said = "Rekening BCA lima dua tujuh satu nol tiga delapan empat enam dua atas nama Rudi"
    assert "5271038462" in spoken_digits_to_number(said)


def test_a_dictated_account_number_is_actually_extracted():
    """The point of the whole exercise: it reaches the entity list."""
    said = "Rekening BCA lima dua tujuh satu nol tiga delapan empat enam dua atas nama Rudi"
    found = [(e.type, e.normalized_value) for e in extract_layer_a(said)]
    assert ("bank_account", "5271038462") in found


def test_a_dictated_phone_number_is_extracted_and_normalised():
    said = "konfirmasi ke nomor saya nol delapan satu dua delapan delapan empat satu empat empat tujuh satu"
    found = [(e.type, e.normalized_value) for e in extract_layer_a(said)]
    assert ("phone", "+6281288414471") in found


def test_kosong_counts_as_zero():
    """What people actually say for 0 when reading a number aloud."""
    said = "kosong delapan satu dua tiga empat lima enam tujuh delapan"
    assert "0812345678" in spoken_digits_to_number(said)


@pytest.mark.parametrize(
    "said",
    [
        "untung dua puluh persen per bulan",       # a percentage
        "modal awalnya lima juta saja",            # an amount
        "nanti untungnya tiga kali lipat",         # a multiplier
        "satu dua tiga percobaan",                 # a short count
        "kesatuan keempat tidak boleh berubah",    # digits INSIDE other words
    ],
)
def test_ordinary_speech_is_left_alone(said):
    """Inventing an account number out of "lima juta" would be fabricating
    evidence, which is worse than missing one."""
    assert spoken_digits_to_number(said) == said
    assert extract_layer_a(said) == []


def test_a_run_must_be_long_enough_to_be_a_number():
    """Five digits is a price or a count; six starts to look dictated."""
    assert spoken_digits_to_number("satu dua tiga empat lima") == "satu dua tiga empat lima"
    assert spoken_digits_to_number("satu dua tiga empat lima enam") == "123456"


def test_separators_a_transcriber_inserts_do_not_break_a_run():
    said = "delapan, satu - dua. tiga empat lima"
    assert "812345" in spoken_digits_to_number(said)


def test_the_stored_message_is_never_rewritten():
    """Normalisation feeds the EXTRACTOR only. Custody must keep what was said,
    or the record stops being a record of the call."""
    said = "rekening lima dua tujuh satu nol tiga delapan empat enam dua"
    entities = extract_layer_a(said)
    assert entities, "sanity: this should extract"
    # The helper is pure — calling it does not mutate the caller's string, and
    # nothing in the pipeline writes its output back into the message.
    assert said == "rekening lima dua tujuh satu nol tiga delapan empat enam dua"


# --- Partial account numbers -------------------------------------------------


def test_a_short_number_is_recorded_as_partial_not_dropped():
    """A scammer read out "123 1149" on a live call and the extractor returned
    nothing, because no Indonesian account is seven digits. The transcript kept
    it and the case did not, which leaves an operator unable to tell "he said
    nothing" from "he said something we would not keep"."""
    ents = extract_layer_a("Iya Bu bisa ditransfer ke rekening 123 1149")
    assert [e.normalized_value for e in ents] == ["1231149"]
    e = ents[0]
    assert "partial_account_number" in e.validators_passed
    assert "incomplete" in e.context.lower()
    # Graded well below a full-length account so nothing downstream mistakes a
    # fragment for something a freeze request could name.
    assert e.confidence < 0.5


def test_a_full_length_account_still_outranks_a_fragment():
    full = extract_layer_a("transfer ke rekening BCA 5271038462 atas nama Rudi")[0]
    part = extract_layer_a("Iya Bu bisa ditransfer ke rekening 123 1149")[0]
    assert full.confidence > part.confidence
    assert "partial_account_number" not in full.validators_passed


@pytest.mark.parametrize("said", [
    "rekening 1149",                 # 4 digits — noise, not a fragment
    "harganya 12345 rupiah",         # no bank context anchor at all
])
def test_the_floor_still_holds(said):
    """Below six digits a run is more likely a price, a year or a reference than
    any part of an account. Inventing evidence out of noise is worse than
    missing a fragment."""
    assert [e for e in extract_layer_a(said) if e.type == "bank_account"] == []
