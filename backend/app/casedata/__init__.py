"""CASEDATA — analyst-entered case records that feed the existing engines.

Two tracked record types an investigator can add by hand:

- **Bank accounts** (``casedata.bank_accounts``) — surfaced on the TRACE Bridge
  as a watchlist, flagged when they appear in the generated flow.
- **Crypto transfers** (``casedata.crypto_transfers``) — merged into the
  TAKEDOWN investigation graph, so a hand-entered transaction (or a brand-new
  wallet) becomes investigable exactly like fixture/live data.

Same dual-persistence pattern as INFILTRATE (docs/Persistence-Plan.md):
in-memory singleton for POC, agency-scoped Postgres + RLS when
``ITTU_PERSISTENCE=postgres``.
"""
