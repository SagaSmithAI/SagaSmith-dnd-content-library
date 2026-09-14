"""Validate the complete private current-Pack collection using only stdlib."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, BinaryIO

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
PINNED_DEFINITION_CHECKSUMS = {
    (
        "dnd5e.addon.rulebook.d-d-5e-sword-coast-adventurer-s-guide.16e6a243ef0a.addon",
        "1.0.5-local.subclass-grants.1",
    ): {
        "dnd5e.addon.rulebook.d-d-5e-sword-coast-adventurer-s-guide.16e6a243ef0a": (
            "c091c39cf03443e40f7b76a0de561298a0527fddff5c83d51fc0660fcbbd70eb"
        )
    }
}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _stream_digest(stream: BinaryIO) -> tuple[int, str]:
    """Validate large archives and blobs without retaining their entire bytes."""
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(1024 * 1024):
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def _definition_checksum(
    *,
    manifest: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
    mechanics: Sequence[Mapping[str, Any]],
) -> str:
    def native_records(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                key: value
                for key, value in dict(item).items()
                if key != "rule_definition_id"
            }
            for item in items
        ]

    encoded = json.dumps(
        {
            "manifest": dict(manifest),
            "artifacts": native_records(artifacts),
            "mechanics": native_records(mechanics),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_pinned_definitions(package: dict[str, Any], *, path_text: str) -> None:
    expected = PINNED_DEFINITION_CHECKSUMS.get(
        (str(package.get("id")), str(package.get("version")))
    )
    if expected is None:
        return
    content = package.get("content") or {}
    definitions = content.get("rule_definitions") or []
    if len(definitions) != len(expected) or {
        str(item.get("id")) for item in definitions
    } != set(expected):
        raise ValueError(f"pinned rule-definition set differs: {path_text}")
    artifacts = content.get("artifacts") or []
    mechanics = content.get("mechanics") or []
    for definition in definitions:
        definition_id = str(definition["id"])
        recomputed = _definition_checksum(
            manifest=definition["manifest"],
            artifacts=[
                item
                for item in artifacts
                if str(item.get("rule_definition_id") or "") == definition_id
            ],
            mechanics=[
                item
                for item in mechanics
                if str(item.get("rule_definition_id") or "") == definition_id
            ],
        )
        if recomputed != expected[definition_id]:
            raise ValueError(f"pinned rule-definition input drift: {path_text}")
        if definition.get("definition_checksum") != recomputed:
            raise ValueError(f"stale rule-definition checksum: {path_text}")


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

    evidence_identities = {
        key: {
            (str(item.get("id")), str(item.get("kind")), str(item.get("checksum")))
            for item in evidence[key]
        }
        for key in ("dnd", "coc")
    }
    indexed_identities = {
        "dnd": {
            (str(item["id"]), str(item["kind"]), str(item["checksum"]))
            for item in indexed
            if item["system_id"] == "dnd5e"
        },
        "coc": {
            (str(item["id"]), str(item["kind"]), str(item["checksum"]))
            for item in indexed
            if item["system_id"] == "coc7e"
        },
    }
    if evidence_identities != indexed_identities:
        raise ValueError(
            "public MCP import evidence does not match current Pack identities"
        )

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
        with archive_path.open("rb") as stream:
            archive_size, archive_digest = _stream_digest(stream)
        total_bytes += archive_size
        if archive_size != int(item["archive_size"]):
            raise ValueError(f"archive size mismatch: {path_text}")
        if archive_digest != item["archive_sha256"]:
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
            _validate_pinned_definitions(package, path_text=path_text)
            assets = {str(asset["checksum"]): asset for asset in package["assets"]}
            blob_names = {
                name.removeprefix("blobs/sha256/")
                for name in names
                if name.startswith("blobs/sha256/")
            }
            if blob_names != set(assets):
                raise ValueError(f"archive blob set is incomplete: {path_text}")
            for checksum, asset in assets.items():
                with archive.open(f"blobs/sha256/{checksum}") as stream:
                    blob_size, blob_digest = _stream_digest(stream)
                if blob_size != int(asset["size"]):
                    raise ValueError(f"blob size mismatch: {path_text}:{checksum}")
                if blob_digest != checksum:
                    raise ValueError(f"blob checksum mismatch: {path_text}:{checksum}")
            for dependency in package["dependencies"]:
                if (
                    not dependency["optional"]
                    and dependency["checksum"] not in checksum_set
                ):
                    raise ValueError(f"required dependency is absent: {package['id']}")
        counts[f"{item['system_id']}:{item['kind']}"] += 1

    retained = [
        item
        for item in report.get("superseded_archives") or []
        if item.get("retained_finalized") is True
    ]
    retained_bytes = 0
    for item in retained:
        path_text = str(item["path"])
        if "\\" in path_text or Path(path_text).is_absolute():
            raise ValueError(f"non-portable retained Pack path: {path_text}")
        archive_path = (ROOT / path_text).resolve()
        if archive_path.parent != (ROOT / "packages").resolve():
            raise ValueError(
                f"retained Pack path escapes packages directory: {path_text}"
            )
        if archive_path in expected_files:
            raise ValueError(f"retained Pack is also indexed as current: {path_text}")
        expected_files.add(archive_path)
        with archive_path.open("rb") as stream:
            archive_size, archive_digest = _stream_digest(stream)
        retained_bytes += archive_size
        if archive_size != int(item["archive_size"]):
            raise ValueError(f"retained archive size mismatch: {path_text}")
        if archive_digest != item["archive_sha256"]:
            raise ValueError(f"retained archive checksum mismatch: {path_text}")
        with zipfile.ZipFile(archive_path) as archive:
            package = json.loads(archive.read(DESCRIPTOR))
        identity = item.get("identity") or []
        if len(identity) != 3 or any(
            package[field] != expected
            for field, expected in zip(
                ("system_id", "kind", "id"), identity, strict=True
            )
        ):
            raise ValueError(
                f"retained archive identity differs from report: {path_text}"
            )
        if (
            package["version"] != item["version"]
            or package["checksum"] != item["checksum"]
        ):
            raise ValueError(
                f"retained archive version differs from report: {path_text}"
            )
        replacement = item.get("superseded_by") or {}
        if not any(
            current["id"] == package["id"]
            and current["version"] == replacement.get("version")
            and current["checksum"] == replacement.get("checksum")
            for current in indexed
        ):
            raise ValueError(
                f"retained archive replacement is not current: {path_text}"
            )

    actual_files = {
        path.resolve() for path in (ROOT / "packages").iterdir() if path.is_file()
    }
    if actual_files != expected_files:
        raise ValueError("packages directory contains stale or missing files")
    if dict(sorted(counts.items())) != EXPECTED_COUNTS:
        raise ValueError(f"unexpected current Pack counts: {dict(counts)}")
    archive_summary = summary.get("archive_validation") or {}
    if (
        archive_summary.get("archives") != 46
        or archive_summary.get("bytes") != total_bytes
    ):
        raise ValueError("validation summary does not match current archives")
    if (
        archive_summary.get("retained_superseded_archives") != len(retained)
        or archive_summary.get("retained_superseded_bytes") != retained_bytes
        or archive_summary.get("stored_archives") != len(expected_files)
        or archive_summary.get("stored_bytes") != total_bytes + retained_bytes
    ):
        raise ValueError("validation summary does not match retained archives")
    print(
        json.dumps(
            {
                "packages": len(indexed),
                "bytes": total_bytes,
                "retained_packages": len(retained),
                "retained_bytes": retained_bytes,
                "counts": dict(sorted(counts.items())),
                "validated": True,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
