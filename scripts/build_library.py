"""Rebuild the static index and browsable blobs from unified content archives."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO.parent
for source_root in (
    WORKSPACE / "sagasmith-core" / "src",
    WORKSPACE / "sagasmith-dnd" / "src",
):
    sys.path.insert(0, str(source_root))

from sagasmith_core.content_pack import loads_content_archive
from sagasmith_dnd.public_library import build_public_library


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=REPO / "public" / "content-library" / "packages",
        help="directory containing .sagasmith-pack archives",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "public" / "content-library",
    )
    args = parser.parse_args()
    packages = []
    archives: dict[str, bytes] = {}
    for path in sorted(args.input.glob("*.sagasmith-pack")):
        content = path.read_bytes()
        package, _blobs = loads_content_archive(content)
        packages.append(package)
        archives[package["checksum"]] = content
    if not packages:
        raise SystemExit(f"no unified content archives found in {args.input}")
    index = build_public_library(args.output, packages, archives=archives)
    print(json.dumps({"packages": len(index["packages"])}, indent=2))


if __name__ == "__main__":
    main()
