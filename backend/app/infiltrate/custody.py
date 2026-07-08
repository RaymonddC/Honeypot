"""Chain-of-custody for honeypot messages — SHA-256 hash-chain per session.

Every raw message is evidence from message #1: hashed, timestamped, and linked
(``sha256`` + ``prev_sha256``) into an append-only, tamper-evident chain
(docs/INFILTRATE-Design.md §9, docs/Data-Model.md intel.messages). Any
alteration to content/order is detectable — meets the UU ITE Pasal 5
electronic-evidence standard.

Reuses the primitive from UNCOVER (``app/uncover/custody.py``): the same
``sha256_hex`` + ``GENESIS`` and the identical canonical-JSON link recipe, so
honeypot custody and document custody share one verified hashing scheme.
"""

import json
from datetime import datetime

from pydantic import BaseModel

from app.uncover.custody import GENESIS, sha256_hex


class ChainedMessage(BaseModel):
    """A message with its custody link (hex-encoded hashes for JSON transport)."""

    seq: int
    session_id: str
    direction: str            # inbound | outbound
    content: str
    ts: datetime
    sha256: str               # hex
    prev_sha256: str          # hex (genesis = 64 zeros)
    meta: dict = {}


def message_hash(
    seq: int, session_id: str, direction: str, content: str,
    ts: datetime, prev_sha256: str,
) -> str:
    """Canonical SHA-256 link over the immutable message fields (hex)."""
    canonical = json.dumps(
        {
            "seq": seq,
            "session_id": session_id,
            "direction": direction,
            "content": content,
            "ts": ts.isoformat(),
            "prev_sha256": prev_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256_hex(canonical.encode())


class MessageChain:
    """Append-only, hash-chained message log for one session (in-memory, POC)."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._messages: list[ChainedMessage] = []

    def append(
        self, direction: str, content: str, ts: datetime, meta: dict | None = None
    ) -> ChainedMessage:
        seq = len(self._messages) + 1
        prev = self._messages[-1].sha256 if self._messages else GENESIS
        sha = message_hash(seq, self.session_id, direction, content, ts, prev)
        msg = ChainedMessage(
            seq=seq, session_id=self.session_id, direction=direction, content=content,
            ts=ts, sha256=sha, prev_sha256=prev, meta=meta or {},
        )
        self._messages.append(msg)
        return msg

    def messages(self) -> list[ChainedMessage]:
        return list(self._messages)

    @property
    def head(self) -> str:
        return self._messages[-1].sha256 if self._messages else GENESIS

    def verify(self) -> bool:
        """Recompute every link — True iff the chain is untampered."""
        prev = GENESIS
        for m in self._messages:
            if m.prev_sha256 != prev:
                return False
            expected = message_hash(
                m.seq, m.session_id, m.direction, m.content, m.ts, m.prev_sha256
            )
            if m.sha256 != expected:
                return False
            prev = m.sha256
        return True
