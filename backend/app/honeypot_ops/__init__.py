"""HONEYPOT OPS — the operational layer around outbound honeypot calling.

Design spec: ``docs/Voice-Honeypot-Outbound.md``. Where INFILTRATE owns the
*conversation* (persona, extraction, custody, clustering), this module owns the
*logistics* of getting a call to happen at all:

- **Numbers** (``honeypot.numbers``) — the pool of Twilio numbers we dial FROM,
  rotated so a burned caller-ID doesn't kill the operation. Registered by an
  operator (bought/configured in the Twilio console), never provisioned via API
  — see the settled decision in the design spec §9.
- **Campaigns** (``honeypot.dial_campaigns``) — one uploaded batch of scammer
  numbers to work through, with a pacing cap.
- **Targets** (``honeypot.dial_targets``) — one row per number in a campaign,
  carrying the durable dial status/retry bookkeeping (the same shape
  ``action.notifications`` uses for webhook delivery).

**This package is currently SCHEMA ONLY** (design spec phase 1): models +
migration, no router/service/worker yet. Those land in phases 3–4.

⚠️ Legal posture (design spec §0): dialing a *real reported scam number* is
engaging a real suspect and stays behind the same Polri-authorization gate as
``PstnChannelAdapter``. Nothing here removes that gate — the tables exist so the
pipeline can be built and demoed against self-test numbers.
"""
