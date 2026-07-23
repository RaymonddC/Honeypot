#!/usr/bin/env python
"""CLI: validate the TAKEDOWN Isolation Forest against the Elliptic Data Set.

Uses the real 203k-tx CSVs when available (``--data-dir`` or ``ITTU_ELLIPTIC_DIR``),
otherwise a schema-accurate synthetic sample so it always runs. Prints a metrics
report (ROC-AUC / precision / recall / F1 / confusion) and, with ``--json``,
emits the machine-readable ``EllipticValidationReport``.

    python scripts/validate_elliptic.py
    ITTU_ELLIPTIC_DIR=/data/elliptic python scripts/validate_elliptic.py --json
    python scripts/validate_elliptic.py --data-dir /data/elliptic --contamination 0.1
"""

import argparse
import sys
from pathlib import Path

# Allow running as a bare script (python scripts/validate_elliptic.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.takedown.elliptic import (  # noqa: E402
    DEFAULT_CONTAMINATION,
    _format_report,
    run_validation,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--data-dir",
        default=None,
        help="Directory holding the real Elliptic CSVs "
        "(else ITTU_ELLIPTIC_DIR, else the synthetic fallback).",
    )
    ap.add_argument(
        "--contamination",
        type=float,
        default=DEFAULT_CONTAMINATION,
        help=f"Isolation Forest contamination (default {DEFAULT_CONTAMINATION}).",
    )
    ap.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    args = ap.parse_args()

    report = run_validation(data_dir=args.data_dir, contamination=args.contamination)
    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(_format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
