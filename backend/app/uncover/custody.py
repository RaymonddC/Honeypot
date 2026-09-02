"""Evidence hashing — SHA-256 over document bytes (UNCOVER).

**This module used to own a second audit chain. It no longer does.**

``uncover.custody.audit_log`` was a per-PROCESS, in-memory, hash-chained log that
existed to fill ``ActionBundle.audit``. Its docstring argued for keeping it
separate from ``core.audit_log`` on the grounds that the two were different
things. That argument is superseded, and it was hiding a real defect:

* It did not survive a restart, and Render restarts. So a bundle's custody view
  was empty after every deploy — and the Action Panel derived the displayed
  **evidence hash** from that chain's head, falling back to the first document's
  hash when the chain was empty. The SAME bundle therefore showed one evidence
  hash before a restart and a different one after. For a product whose pitch is
  chain of custody, an evidence hash that silently changes is worse than none.
* It recorded strictly LESS than the core trail already did. ``core.audit_log``
  had carried ``action.bundle.generated`` and ``dispatch.sent`` against the
  bundle since the durable-evidence work, with the actor's id and name, origin
  (``_ip``/``_user_agent``/``_request_id``) and every document sha256.

``ActionBundle.audit`` is now a filtered, agency-scoped view of ``core.audit_log``
(see ``_attach_audit`` in ``app/uncover/router.py``): durable, tamper-evident,
verified on read at ``GET /api/audit``, and — because denials are recorded too —
now able to show a REFUSED dispatch, which the custody chain never could.

What remains here is document hashing, which was always a separate concern:
every generated PDF is SHA-256 hashed as evidence in its own right
(``action_documents.sha256``), independent of any chain. ``GENESIS`` stays too —
``app/infiltrate/custody.py`` builds its per-session message chain on the same
primitive. UU ITE Pasal 5 posture is unchanged: alteration remains detectable,
now in the one log that outlives the process.
"""

import hashlib

# The zero hash every chain starts from. Shared with app/infiltrate/custody.py,
# which uses the identical canonical-JSON link recipe for message chains.
GENESIS = "0" * 64


def sha256_hex(data: bytes) -> str:
    """SHA-256 of raw bytes as lowercase hex (custody hash for documents)."""
    return hashlib.sha256(data).hexdigest()
