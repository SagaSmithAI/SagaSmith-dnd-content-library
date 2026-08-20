"""Validate every committed long-regression evidence record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from export_regression_evidence import validate_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_dir", type=Path)
    args = parser.parse_args()
    paths = sorted(args.evidence_dir.glob("*.json"))
    if not paths:
        raise ValueError("no regression evidence records found")
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError(f"{path} must contain a JSON object")
        validate_evidence(value)
        print(f"OK {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
