"""Publish canonical replacements for the affected official D&D actor Packs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sagasmith_core.content_pack import (
    build_content_package,
    dumps_content_archive,
    loads_content_archive,
)
from sagasmith_dnd.content_packages import (
    canonicalize_dnd_content_package,
    validate_dnd_content_package,
)

ROOT = Path(__file__).resolve().parents[1] / "content-library"
SOURCE_IDENTITIES = {
    "dnd5e.addon.rulebook.d-d-5e-eberron-rising-from-the-last-war.31293633134f.addon": (
        "1.0.1",
        "208e603266337eca76b52e036bd8ecca95c48ffa02c910dd006f445c5b868e7e",
    ),
    "dnd5e.addon.rulebook.d-d-5e-guildmasters-guide-to-ravnica.59317c5cf3da.addon": (
        "1.0.1",
        "852a5d488e25745daa6f4633fa14af00849fab71a8f1f050ad428946f2f36e83",
    ),
    "dnd5e.addon.rulebook.d-d-5e-mordenkainen-s-tome-of-foes.2768304ef1af.addon": (
        "1.0.1",
        "f4fb310143b6c908f528c60e6db0eab0cd0120cdc576c302a565a83dc8ac7e13",
    ),
    "dnd5e.addon.rulebook.d-d-5e-volo-s-guide-to-monsters.962933255634.addon": (
        "1.0.1",
        "58a355611d7a685f60bca9620bf84cdfcd0310f4b98a6059a3c8488aafaa06f4",
    ),
}
TARGET_IDS = frozenset(SOURCE_IDENTITIES)


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _write_object(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _next_patch(version: str) -> str:
    parts = version.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f"cannot bump non-semantic version: {version}")
    major, minor, patch = (int(part) for part in parts)
    return f"{major}.{minor}.{patch + 1}"


def _rebuild_package(package: dict[str, Any]) -> dict[str, Any]:
    canonical = canonicalize_dnd_content_package(package)
    next_version = _next_patch(str(package["version"]))
    rebuilt = build_content_package(
        kind=str(canonical["kind"]),
        package_id=str(canonical["id"]),
        version=next_version,
        system_id=str(canonical["system_id"]),
        manifest=canonical["manifest"],
        dependencies=canonical["dependencies"],
        sources=canonical["sources"],
        assets=canonical["assets"],
        content_reviews=canonical["content_reviews"],
        actors=canonical["actors"],
        content=canonical["content"],
        metadata=canonical["metadata"],
    )
    return validate_dnd_content_package(rebuilt)


def main() -> None:
    index_path = ROOT / "index.json"
    report_path = ROOT / "migration-report.json"
    summary_path = ROOT / "validation-summary.json"
    index = _read_object(index_path)
    report = _read_object(report_path)
    summary = _read_object(summary_path)
    packages = list(index.get("packages") or [])
    by_id = {
        str(item.get("id") or ""): item for item in packages if isinstance(item, dict)
    }
    if set(by_id).issuperset(TARGET_IDS) is False:
        missing = sorted(TARGET_IDS - set(by_id))
        raise ValueError("target Packs are absent: " + ", ".join(missing))

    replacements: dict[str, dict[str, Any]] = {}
    old_paths: list[Path] = []
    for package_id in sorted(TARGET_IDS):
        item = dict(by_id[package_id])
        source_version, source_checksum = SOURCE_IDENTITIES[package_id]
        if item.get("checksum") != source_checksum:
            if (
                item.get("action") == "canonicalized_current"
                and item.get("source_version") == source_version
                and item.get("source_checksum") == source_checksum
                and item.get("version") == _next_patch(source_version)
            ):
                replacements[package_id] = item
                continue
            raise ValueError(f"target Pack has an unexpected current identity: {package_id}")
        old_path = (ROOT / str(item["path"])).resolve()
        package_root = (ROOT / "packages").resolve()
        if old_path.parent != package_root or not old_path.is_file():
            raise ValueError(f"target archive is outside packages/: {item['path']}")
        package, blobs = loads_content_archive(old_path.read_bytes())
        if (
            package.get("id") != package_id
            or package.get("version") != item.get("version")
            or package.get("checksum") != item.get("checksum")
        ):
            raise ValueError(f"target archive identity is stale: {package_id}")
        rebuilt = _rebuild_package(package)
        archive = dumps_content_archive(rebuilt, blobs)
        archive_sha256 = hashlib.sha256(archive).hexdigest()
        filename = (
            f"{rebuilt['checksum'][:12]}-{rebuilt['id']}-{rebuilt['version']}"
            ".sagasmith-pack"
        )
        new_path = (package_root / filename).resolve()
        if new_path.parent != package_root or new_path == old_path:
            raise ValueError(f"invalid replacement path for {package_id}")
        if new_path.exists() and new_path.read_bytes() != archive:
            raise RuntimeError(f"replacement archive already exists with other bytes: {filename}")
        new_path.write_bytes(archive)
        replacement = {
            **item,
            "action": "canonicalized_current",
            "source_version": source_version,
            "source_checksum": source_checksum,
            "version": str(rebuilt["version"]),
            "checksum": str(rebuilt["checksum"]),
            "archive_sha256": archive_sha256,
            "archive_size": len(archive),
            "source_path": str(item["path"]),
            "path": f"packages/{filename}",
        }
        replacements[package_id] = replacement
        old_paths.append(old_path)

    updated = [replacements.get(str(item.get("id") or ""), item) for item in packages]
    index["generated_on"] = "2026-08-30"
    index["packages"] = updated
    report["packages"] = updated
    total_bytes = sum(
        (ROOT / str(item["path"])).stat().st_size for item in updated
    )
    archive_validation = dict(summary.get("archive_validation") or {})
    archive_validation["bytes"] = total_bytes
    summary["archive_validation"] = archive_validation
    _write_object(index_path, index)
    _write_object(report_path, report)
    _write_object(summary_path, summary)
    for old_path in old_paths:
        old_path.unlink()
    print(
        json.dumps(
            {
                "published": len(old_paths),
                "packages": sorted(replacements),
                "bytes": total_bytes,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
