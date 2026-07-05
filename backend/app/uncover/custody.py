"""Evidence & custody — SHA-256 hashing + hash-chained audit log (UNCOVER).

Every generated document is evidence: hashed, timestamped, and recorded in an
append-only, tamper-evident audit chain (``sha256`` + ``prev_sha256``),
mirroring ``core.audit_log`` in docs/Data-Model.md. POC keeps the chain
in-memory (same in-memory pattern as P1/P2 endpoints); the table is the
persistence target for later phases. Meets the UU ITE Pasal 5
electronic-evidence posture: any alteration is detectable.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel

GENESIS = "0" * 64


def sha256_hex(data: bytes) -> str:
    """SHA-256 of raw bytes as lowercase hex (custody hash for documents)."""
    return hashlib.sha256(data).hexdigest()


class AuditEntry(BaseModel):
    id: str
    seq: int
    action: str                # e.g. "action.documents.generated"
    target_type: str           # action_document | action_bundle | notification
    target_id: str
    detail: dict
    ts: datetime
    sha256: str
    prev_sha256: str


class AuditLog:
    """Append-only, hash-chained audit log (in-memory, POC)."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    @staticmethod
    def _entry_hash(
        seq: int, action: str, target_type: str, target_id: str,
        detail: dict, ts: datetime, prev_sha256: str,
    ) -> str:
        canonical = json.dumps(
            {
                "seq": seq,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "detail": detail,
                "ts": ts.isoformat(),
                "prev_sha256": prev_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return sha256_hex(canonical.encode())

    def record(
        self, action: str, target_type: str, target_id: str, detail: dict | None = None
    ) -> AuditEntry:
        detail = detail or {}
        seq = len(self._entries) + 1
        prev = self._entries[-1].sha256 if self._entries else GENESIS
        ts = datetime.now(timezone.utc)
        entry = AuditEntry(
            id=uuid.uuid4().hex,
            seq=seq,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            ts=ts,
            sha256=self._entry_hash(seq, action, target_type, target_id, detail, ts, prev),
            prev_sha256=prev,
        )
        self._entries.append(entry)
        return entry

    def entries(self) -> list[AuditEntry]:
        return list(self._entries)

    def for_target(self, target_id: str) -> list[AuditEntry]:
        return [e for e in self._entries if e.target_id == target_id]

    def verify_chain(self) -> bool:
        """Recompute every link — True iff the chain is untampered."""
        prev = GENESIS
        for e in self._entries:
            if e.prev_sha256 != prev:
                return False
            expected = self._entry_hash(
                e.seq, e.action, e.target_type, e.target_id, e.detail, e.ts, e.prev_sha256
            )
            if e.sha256 != expected:
                return False
            prev = e.sha256
        return True

    def reset(self) -> None:  # test hook
        self._entries.clear()


# Module-level singleton (POC — one process, one chain).
audit_log = AuditLog()
