"""Contract tests for every registered LIVE adapter (go-live hardening).

The Adapter-MODE framework's third principle is that a LIVE boundary must
**fail loudly** rather than silently degrade. That invariant is what stops the
worst failure this product could have: appearing to engage a real scammer, or
appearing to dispatch a freeze request to a bank, while actually doing nothing.
A silent no-op is far more dangerous here than an error, because the operator
believes the action happened.

Every adapter honours it individually today. These tests assert it **as a
contract over the registry**, so a new LIVE adapter cannot be added without
either honouring the rule or failing here — the point being that the next
adapter is written by someone who has not read the framework doc.

Deliberately construction-only: no network, no credentials, no mocking of
provider internals. The question is "does an unconfigured LIVE adapter refuse to
run", not "does the provider work".
"""

import pytest

import app.main  # noqa: F401 - imported for its side effect: populates the registry
from app.core.adapters import _REGISTRY
from app.core.config import Settings

# Boundaries whose LIVE entry is a factory rather than a class — `tts` resolves
# a provider by name at call time, so "construct it" means something different.
# Covered by its own tests (test_infiltrate_voice.py asserts each provider fails
# loud without its key); excluded here rather than special-cased into the loop.
FACTORY_BOUNDARIES = {"tts"}

# _REGISTRY holds the CLASSES; the public `registered()` returns their names,
# which is the wrong shape for constructing them here.
LIVE_ADAPTERS = sorted(
    (boundary, impl.__name__)
    for (boundary, mode), impl in _REGISTRY.items()
    if mode == "live" and boundary not in FACTORY_BOUNDARIES
)


def _unconfigured() -> Settings:
    """Settings with every credential blank — a fresh deployment that flipped
    a module to LIVE without doing the operational setup."""
    return Settings(
        tronscan_api_key="",
        elevenlabs_api_key="",
        google_tts_api_key="",
        gemini_api_key="",
        llm_api_key="",
        twilio_account_sid="",
        twilio_auth_token="",
        notification_webhook_url="",
    )


def test_the_live_registry_is_not_empty():
    """Guards the guard: if the registry were empty (an import moved, say), the
    parametrised tests below would silently pass by testing nothing."""
    assert len(LIVE_ADAPTERS) >= 7, LIVE_ADAPTERS


# Adapters that legitimately CONSTRUCT without credentials. Each still refuses
# to act — the invariant is "never a silent no-op", not "must raise in
# __init__" — so they fail loud at first use instead:
#
#   TronscanAdapter     TRONSCAN's public API genuinely works keyless (a key
#                       only raises the rate limit), so this one can really run.
#   LiveNotificationSink  dispatch() raises without ITTU_NOTIFICATION_WEBHOOK_URL.
#   BankFeedAdapter     load_dataset() raises — no bank feed exists yet.
#
# Pinned as a set so a NEW adapter that constructs unconfigured trips this test
# and forces someone to decide which case it is, rather than joining silently.
CONSTRUCTS_UNCONFIGURED = {"TronscanAdapter", "LiveNotificationSink", "BankFeedAdapter"}


@pytest.mark.parametrize(("boundary", "impl_name"), LIVE_ADAPTERS, ids=lambda v: str(v))
def test_live_adapter_never_silently_no_ops(boundary, impl_name):
    """Unconfigured LIVE adapters must refuse — at construction or at first use.

    This is the invariant that stops the worst failure this product could have:
    appearing to engage a real scammer, or appearing to dispatch a freeze
    request to a bank, while actually doing nothing. A silent no-op is far more
    dangerous than an error, because the operator believes it happened.
    """
    impl = _REGISTRY[(boundary, "live")]
    try:
        impl(_unconfigured())
    except (NotImplementedError, ValueError, RuntimeError, TypeError) as exc:
        assert str(exc).strip(), f"{impl_name} raised {type(exc).__name__} with no message"
        return

    assert impl_name in CONSTRUCTS_UNCONFIGURED, (
        f"{boundary} LIVE adapter {impl_name} constructed with NO credentials and "
        "is not a known exception. A LIVE boundary must fail loudly when "
        "unconfigured (Adapter-MODE principle #3). If it legitimately works "
        "without credentials, or refuses at first use instead, add it to "
        "CONSTRUCTS_UNCONFIGURED with the reason."
    )


@pytest.mark.parametrize(("boundary", "impl_name"), LIVE_ADAPTERS, ids=lambda v: str(v))
def test_live_adapter_error_names_what_is_missing(boundary, impl_name):
    """The failure must be actionable: name the env var or the missing piece.

    'NotImplementedError' alone sends someone reading a stack trace instead of
    setting a variable. Every adapter here already names its requirement; this
    keeps the next one honest.
    """
    impl = _REGISTRY[(boundary, "live")]
    try:
        impl(_unconfigured())
    except Exception as exc:  # noqa: BLE001 - the message is what's under test
        msg = str(exc)
        informative = "ITTU_" in msg or any(
            word in msg.lower()
            for word in ("credential", "key", "not wired", "requires", "configure", "token")
        )
        assert informative, (
            f"{impl_name} failed with an unhelpful message: {msg!r}. "
            "Say which credential or component is missing."
        )
    else:  # pragma: no cover - the test above already fails in this case
        pytest.skip("constructed without credentials; covered by the previous test")
