"""Compare the public catalog marker with the catalog currently on main.

The public site publishes a small marker containing the exact catalog commit
and generation date.  This check deliberately validates that marker against the
latest commit that changed ``content-library/index.json``; it does not infer
freshness from a deployment timestamp or from repository visibility.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen


DEFAULT_STATUS_URL = (
    "https://sagasmithai.github.io/library-catalog-status.json"
)


def _read_json(url: str, *, timeout: float) -> dict[str, object]:
    request = Request(url, headers={"User-Agent": "SagaSmith-catalog-check/1"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - explicit HTTPS URLs
        value = json.load(response)
    if not isinstance(value, dict):
        raise ValueError(f"{url} must return a JSON object")
    return value


def _latest_catalog_commit() -> str:
    result = subprocess.run(
        [
            "git",
            "log",
            "-1",
            "--format=%H",
            "--",
            "content-library/index.json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip()
    if len(commit) != 40:
        raise ValueError("could not resolve the catalog source commit")
    return commit


def check(*, status_url: str, timeout: float) -> dict[str, str]:
    status = _read_json(status_url, timeout=timeout)
    index = json.loads(
        (Path(__file__).resolve().parents[1] / "content-library" / "index.json").read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(index, dict):
        raise ValueError("content-library/index.json must contain an object")
    generated_on = str(index.get("generated_on") or "")
    source_commit = _latest_catalog_commit()
    published_date = str(status.get("generated_on") or "")
    published_commit = str(status.get("source_commit") or "")
    if published_date != generated_on:
        raise ValueError(
            "published catalog date is stale: "
            f"published={published_date!r}, main={generated_on!r}"
        )
    if published_commit != source_commit:
        raise ValueError(
            "published catalog source commit is stale: "
            f"published={published_commit!r}, main={source_commit!r}"
        )
    return {
        "generated_on": generated_on,
        "source_commit": source_commit,
        "status_url": status_url,
        "fresh": "true",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status-url", default=DEFAULT_STATUS_URL)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    try:
        print(json.dumps(check(status_url=args.status_url, timeout=args.timeout)))
    except Exception as exc:  # pragma: no cover - CLI failure formatting
        print(f"catalog freshness check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
