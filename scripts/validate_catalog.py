"""Validate committed catalog paths, identities, and portable checksums."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "public" / "content-library"


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> None:
    index = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))
    audit = json.loads((ROOT / "audit.json").read_text(encoding="utf-8"))
    expected_paths = set()
    identities = set()
    counts: Counter[str] = Counter()
    for entry in index["packages"]:
        path = ROOT / entry["path"]
        expected_paths.add(path.resolve())
        package = json.loads(path.read_text(encoding="utf-8"))
        unsigned = {key: value for key, value in package.items() if key != "checksum"}
        checksum = hashlib.sha256(canonical_json(unsigned).encode("utf-8")).hexdigest()
        assert checksum == package["checksum"] == entry["checksum"], path
        identity = (package["kind"], package["id"], package["version"])
        assert identity not in identities, identity
        identities.add(identity)
        assert identity == (entry["kind"], entry["id"], entry["version"]), path
        counts[package["kind"]] += 1
    actual_paths = {path.resolve() for path in (ROOT / "packages").glob("*.json")}
    assert actual_paths == expected_paths
    assert sum(counts.values()) == audit["counts"]["total"]
    for kind, count in counts.items():
        assert count == audit["counts"][kind]
    print(json.dumps({"packages": len(identities), "counts": counts}, default=dict))


if __name__ == "__main__":
    main()
