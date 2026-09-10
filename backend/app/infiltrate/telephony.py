"""Twilio telephony primitives — phase 5 groundwork (docs/Live-Voice-Calls.md).

**Nothing here places a call.** This is the part of real telephony that can be
built and *proven correct* without a Twilio account: the pure functions around
the call, not the live media loop. The remaining phase-5 work — the WebSocket
media bridge, streaming STT, and turn-taking/barge-in — is deliberately absent,
because it cannot be honestly tested without real audio and a real carrier, and
a plausible-looking untested media bridge is worse than none.

What is here, and why each earns its place now:

* ``verify_twilio_signature`` — Twilio signs every webhook it sends. Without
  this check, ANY caller who knows the URL can post fake call events and drive
  the honeypot. It is pure crypto with a published test vector, so it can be
  made correct today rather than under deadline once credentials exist.
* ``build_stream_twiml`` — the TwiML that answers a call and opens the media
  stream toward our bridge. Pure string building; the shape is the contract
  with Twilio.
* ``TwilioCallClient`` — places an outbound call via the REST API. Fails loud
  without credentials, exactly like every other LIVE adapter in this codebase.

Credentials are ``ITTU_TWILIO_ACCOUNT_SID`` / ``ITTU_TWILIO_AUTH_TOKEN``; the
number dialled *from* comes from the honeypot number pool
(docs/Voice-Honeypot-Outbound.md §3.1), not from config, because rotation is an
operational decision.

⚠️ Dialling a real reported scam number remains gated on **Polri authorization**
(docs/Voice-Honeypot-Outbound.md §0). Nothing in this module changes that.
"""

import base64
import hashlib
import hmac
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings

_TWILIO_API = "https://api.twilio.com/2010-04-01"


def verify_twilio_signature(
    auth_token: str,
    url: str,
    params: dict[str, str] | None = None,
    signature: str = "",
) -> bool:
    """Validate an ``X-Twilio-Signature`` header. True only if it genuinely matches.

    Algorithm (Twilio "Security" docs): take the full request URL *including*
    its query string, append each POST parameter as ``name`` + ``value`` with no
    delimiter in case-sensitive alphabetical order by name, HMAC-SHA1 the result
    with the account's auth token, and base64 the digest.

    For ``application/json`` webhooks Twilio instead puts a ``bodySHA256`` query
    parameter in the URL and signs no body params — so pass the URL as received
    (with that query parameter intact) and ``params=None``.

    Comparison is constant-time: a byte-by-byte early exit leaks how much of a
    forged signature was correct, which is enough to forge one a byte at a time.

    Returns False rather than raising on a missing token/signature — an
    unconfigured or unsigned request is *not* authentic, and a caller that
    forgets to check an exception should still fail closed.
    """
    if not auth_token or not signature:
        return False
    payload = url + "".join(
        f"{key}{value}" for key, value in sorted((params or {}).items())
    )
    digest = hmac.new(
        auth_token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1
    ).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, signature)


def build_stream_twiml(ws_url: str, *, greeting: str | None = None) -> str:
    """TwiML that answers the call and streams its audio to our media bridge.

    ``<Connect><Stream>`` is **bidirectional** — Twilio sends us the caller's
    audio and plays back what we write to the socket, which is what a live
    persona needs. (``<Start><Stream>`` is a one-way copy: useful for recording,
    useless for conversation.) ``<Connect>`` also holds the call open for the
    life of the socket, so the call ends when the conversation does.

    ``ws_url`` must be ``wss://`` and publicly reachable by Twilio — a localhost
    URL silently never connects, so it is rejected here instead.
    """
    if not ws_url.startswith(("wss://", "ws://")):
        raise ValueError(f"stream URL must be a websocket URL, got {ws_url!r}")
    if ws_url.startswith("ws://"):
        raise ValueError(
            "stream URL must be wss:// — Twilio will not open an unencrypted "
            f"media stream, and call audio is evidence. Got {ws_url!r}"
        )
    say = (
        f"<Say language=\"id-ID\">{_escape(greeting)}</Say>" if greeting else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response>{say}"
        f'<Connect><Stream url="{_escape(ws_url)}"/></Connect>'
        "</Response>"
    )


def build_gather_twiml(
    audio_url: str,
    action_url: str,
    *,
    language: str = "id-ID",
    speech_timeout: str = "auto",
) -> str:
    """Play a line, then listen for the caller's reply. One conversational turn.

    ``<Gather input="speech">`` makes TWILIO do the speech-to-text and POST the
    transcript to ``action_url``. That is the whole reason this path exists: the
    media-stream bridge needs a streaming STT provider we do not have wired
    (``WhisperSTTAdapter`` raises), whereas this needs no provider account at all.

    What it costs is barge-in. ``<Gather>`` is strictly turn-based — the caller
    cannot interrupt the persona mid-sentence the way ``TurnTaker`` allows on the
    media bridge. For a scammer who talks over people that is a real tell, so
    this is the demo-grade path, not the production one.

    ``speech_timeout="auto"`` lets Twilio decide the utterance has ended from the
    audio rather than a fixed silence window; a fixed window either clips people
    who pause to think or leaves dead air after short answers.

    The ``<Redirect>`` after the gather is what happens when the caller says
    NOTHING: Twilio falls through to the next verb. Without it the call would
    simply end on the first silence, which is exactly what a hesitant victim
    sounds like.
    """
    for url, label in ((audio_url, "audio"), (action_url, "action")):
        if not url.startswith("https://"):
            raise ValueError(f"{label} URL must be https://, got {url!r}")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Gather input="speech" language="{_escape(language)}" '
        f'speechTimeout="{_escape(speech_timeout)}" '
        f'action="{_escape(action_url)}" method="POST">'
        f"<Play>{_escape(audio_url)}</Play>"
        "</Gather>"
        f'<Redirect method="POST">{_escape(action_url)}</Redirect>'
        "</Response>"
    )


def build_play_and_hangup_twiml(audio_url: str) -> str:
    """TwiML that plays a synthesized audio file and hangs up.

    The same shape as ``build_say_and_hangup_twiml`` but with OUR voice instead
    of Twilio's built-in one. ``<Say>`` is a generic telephony voice; a honeypot
    persona that sounds like an IVR announces itself as a machine in the first
    two seconds, which is the one thing it cannot afford to do.

    ``audio_url`` must be publicly fetchable — Twilio pulls it over the internet
    with no credentials, so it points at our unauthenticated audio route rather
    than anything behind the JWT. https is required for the same reason the
    media stream is wss: call audio is evidence.
    """
    if not audio_url.startswith("https://"):
        raise ValueError(
            f"audio URL must be https:// and publicly reachable, got {audio_url!r}"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Play>{_escape(audio_url)}</Play><Hangup/></Response>"
    )


def build_say_and_hangup_twiml(message: str, *, language: str = "id-ID") -> str:
    """TwiML that speaks one line and hangs up.

    This is what the answer webhook returns UNTIL the media bridge exists.
    Returning ``<Connect><Stream>`` today would point Twilio at a socket nobody
    is serving, which connects a real caller to silence — worse than an honest
    short call. It also makes the whole Twilio→our-server path verifiable end to
    end (number, webhook, signature, TwiML) without the bridge: ring the number
    and you hear this line.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Response><Say language="{_escape(language)}">{_escape(message)}</Say>'
        "<Hangup/></Response>"
    )


def _escape(text: str | None) -> str:
    """XML-escape a value going into TwiML (a raw ``&`` breaks the document)."""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class TwilioCallClient:
    """Places outbound calls via Twilio's REST API. Fails loud without creds.

    Not wired into the dialer yet — the dialer's LIVE path still raises, because
    a placed call without the media bridge would connect a real person to
    silence. This exists so the request shape is settled and tested before
    credentials arrive.
    """

    def __init__(self, settings: Settings | None = None):
        settings = settings or get_settings()
        self._sid = settings.twilio_account_sid
        self._token = settings.twilio_auth_token
        if not (self._sid and self._token):
            raise NotImplementedError(
                "Twilio is not configured in this build: set "
                "ITTU_TWILIO_ACCOUNT_SID and ITTU_TWILIO_AUTH_TOKEN. Outbound "
                "dialing runs simulated in POC (app/honeypot_ops/dialer.py); "
                "real calls additionally require the phase-5 media bridge and "
                "Polri authorization (docs/Voice-Honeypot-Outbound.md §0)."
            )

    async def place_call(self, *, to: str, from_: str, twiml_url: str) -> dict:
        """POST /Calls — returns Twilio's JSON (``sid``, ``status``, …).

        ``twiml_url`` is fetched by Twilio when the callee answers; it must
        serve the ``build_stream_twiml`` document above.
        """
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{_TWILIO_API}/Accounts/{quote(self._sid)}/Calls.json",
                auth=(self._sid, self._token),
                data={"To": to, "From": from_, "Url": twiml_url},
            )
        if not resp.is_success:
            # Surface Twilio's message (bad number, unverified trial callee,
            # insufficient balance) instead of a bare status code.
            raise RuntimeError(f"Twilio call failed {resp.status_code}: {resp.text[:300]}")
        return resp.json()
