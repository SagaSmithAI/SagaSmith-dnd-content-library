"""Validate the complete private current-Pack collection using only stdlib."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1] / "content-library"
DESCRIPTOR = "package.sagasmith.json"
EXPECTED_COUNTS = {
    "coc7e:core_rules": 1,
    "coc7e:module": 2,
    "dnd5e:addon": 21,
    "dnd5e:core_rules": 2,
    "dnd5e:module": 18,
    "dnd5e:preset": 2,
}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def main() -> None:
    index = _read_json(ROOT / "index.json")
    report = _read_json(ROOT / "migration-report.json")
    summary = _read_json(ROOT / "validation-summary.json")
    evidence = _read_json(ROOT / "import-evidence.json")
    if index.get("schema") != "sagasmith.current-content-packs.v1":
        raise ValueError("index uses an obsolete schema")
    if report.get("schema") != "sagasmith.pack-migration-report.v1":
        raise ValueError("migration report uses an obsolete schema")
    if report.get("unresolved_external_dependencies"):
        raise ValueError("required dependency closure is incomplete")

    indexed = index.get("packages") or []
    reported = report.get("packages") or []
    if indexed != reported or len(indexed) != 46:
        raise ValueError("index and migration report do not describe the same 46 Packs")
    if len(evidence.get("dnd") or []) != 43 or len(evidence.get("coc") or []) != 3:
        raise ValueError("public MCP import evidence is incomplete")
    if not all(
        item.get("idempotent_replay") is True
        for key in ("dnd", "coc")
        for item in evidence[key]
    ):
        raise ValueError("public MCP import retry evidence is incomplete")

    checksum_set = {str(item["checksum"]) for item in indexed}
    counts: Counter[str] = Counter()
    expected_files: set[Path] = set()
    total_bytes = 0
    for item in indexed:
        path_text = str(item["path"])
        if "\\" in path_text or Path(path_text).is_absolute():
            raise ValueError(f"non-portable Pack path: {path_text}")
        archive_path = (ROOT / path_text).resolve()
        if archive_path.parent != (ROOT / "packages").resolve():
            raise ValueError(f"Pack path escapes packages directory: {path_text}")
        expected_files.add(archive_path)
        raw = archive_path.read_bytes()
        total_bytes += len(raw)
        if len(raw) != int(item["archive_size"]):
            raise ValueError(f"archive size mismatch: {path_text}")
        if hashlib.sha256(raw).hexdigest() != item["archive_sha256"]:
            raise ValueError(f"archive checksum mismatch: {path_text}")
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            if DESCRIPTOR not in names:
                raise ValueError(f"archive descriptor is absent: {path_text}")
            package = json.loads(archive.read(DESCRIPTOR))
            if any(
                package[field] != item[field]
                for field in ("id", "version", "checksum", "system_id", "kind")
            ):
                raise ValueError(f"archive identity differs from index: {path_text}")
            assets = {str(asset["checksum"]): asset for asset in package["assets"]}
            blob_names = {
                name.removeprefix("blobs/sha256/")
                for name in names
                if name.startswith("blobs/sha256/")
            }
            if blob_names != set(assets):
                raise ValueError(f"archive blob set is incomplete: {path_text}")
            for checksum, asset in assets.items():
                blob = archive.read(f"blobs/sha256/{checksum}")
                if len(blob) != int(asset["size"]):
                    raise ValueError(f"blob size mismatch: {path_text}:{checksum}")
                if hashlib.sha256(blob).hexdigest() != checksum:
                    raise ValueError(f"blob checksum mismatch: {path_text}:{checksum}")
            for dependency in package["dependencies"]:
                if not dependency["optional"] and dependency["checksum"] not in checksum_set:
                    raise ValueError(f"required dependency is absent: {package['id']}")
        counts[f"{item['system_id']}:{item['kind']}"] += 1

    actual_files = {
        path.resolve() for path in (ROOT / "packages").iterdir() if path.is_file()
    }
    if actual_files != expected_files:
        raise ValueError("packages directory contains stale or missing files")
    if dict(sorted(counts.items())) != EXPECTED_COUNTS:
        raise ValueError(f"unexpected current Pack counts: {dict(counts)}")
    archive_summary = summary.get("archive_validation") or {}
    if archive_summary.get("archives") != 46 or archive_summary.get("bytes") != total_bytes:
        raise ValueError("validation summary does not match stored archives")
    print(
        json.dumps(
            {
                "packages": len(indexed),
                "bytes": total_bytes,
                "counts": dict(sorted(counts.items())),
                "validated": True,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
