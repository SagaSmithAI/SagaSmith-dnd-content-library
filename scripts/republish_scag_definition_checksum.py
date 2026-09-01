"""Publish the immutable SCAG rule-definition checksum correction."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1] / "content-library"
PACKAGE_ID = (
    "dnd5e.addon.rulebook.d-d-5e-sword-coast-adventurer-s-guide.16e6a243ef0a.addon"
)
DEFINITION_ID = PACKAGE_ID.removesuffix(".addon")
SOURCE_VERSION = "1.0.3"
SOURCE_CHECKSUM = "ff8bbff7268d3e9afab5fce2d2ae320422e9d64523c6d2c1c327689dae59a9d9"
SOURCE_ARCHIVE_SHA256 = (
    "1bb977b1a54f9aeb6f31413d7e8918294f2f38a353c48597287ed6ef3d111d2a"
)
SOURCE_ARCHIVE_SIZE = 905648
SOURCE_DEFINITION_CHECKSUM = (
    "b88864495df6d89bb28bf7beef184423c8d38df449cee195b1942862f25c64b9"
)
TARGET_VERSION = "1.0.4"
TARGET_CHECKSUM = "6c5b94c6dd5555af70aa0e987ed84a8f2c4a1124ad228b4e3414867f1a0b83f4"
TARGET_ARCHIVE_SHA256 = (
    "3e2ccfa3d69ecd780770c1f2579326a2e3ce8dbf7324c38c1827304ba9c72ab6"
)
TARGET_ARCHIVE_SIZE = 905806
TARGET_DEFINITION_CHECKSUM = (
    "8b5066a280f5800e24061fbad0b1b11ccf9f2eda4b08de89d8913bb7bc745f44"
)
PUBLISHED_ON = "2026-09-01"
SOURCE_PATH = (
    "packages/ff8bbff7268d-dnd5e.addon.rulebook."
    "d-d-5e-sword-coast-adventurer-s-guide.16e6a243ef0a.addon-1.0.3.sagasmith-pack"
)
TARGET_PATH = (
    "packages/6c5b94c6dd55-dnd5e.addon.rulebook."
    "d-d-5e-sword-coast-adventurer-s-guide.16e6a243ef0a.addon-1.0.4.sagasmith-pack"
)
RUNTIME_DEPENDENCY = {
    "checksum": "3f7508a4177c3dd4a9678d55d55d67a48c282a17f03a0943e092de486f850670",
    "id": "dnd5e.content.srd2014",
    "version": "1.24.0",
}
PRIOR_ARCHIVES = [
    {
        "version": "1.0.1",
        "checksum": "efbba0006ef837961a3d87203c60a49b1ed57428cdb10999aa8b6378964a5bb9",
        "path": (
            "packages/efbba0006ef8-dnd5e.addon.rulebook."
            "d-d-5e-sword-coast-adventurer-s-guide.16e6a243ef0a.addon-1.0.1.sagasmith-pack"
        ),
        "archive_sha256": (
            "d7e755e914f94871b0bf59966109e84f0ae2302776be9127bb558971d8d125d3"
        ),
        "archive_size": 905067,
    },
    {
        "version": "1.0.2",
        "checksum": "5e5504ec3d2ebb82e548a48c6b97f49938ed9d08bf94d6efaa08600a11ab3c22",
        "path": (
            "packages/5e5504ec3d2e-dnd5e.addon.rulebook."
            "d-d-5e-sword-coast-adventurer-s-guide.16e6a243ef0a.addon-1.0.2.sagasmith-pack"
        ),
        "archive_sha256": (
            "63546d562fb921391202e10232733d45e818c71ed1d6cbdd164c11b1fb82359d"
        ),
        "archive_size": 905484,
    },
]


class PublicationConflictError(RuntimeError):
    """Raised before writes when an archive or metadata identity conflicts."""


class InjectedPublicationFailure(RuntimeError):
    """Test-only failure injected immediately after an atomic replacement."""


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PublicationConflictError(f"{path.name} must contain an object")
    return value


def _object_bytes(value: dict[str, Any], *, newline: bytes) -> bytes:
    content = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return content.replace(b"\n", newline)


def _newline_for(content: bytes) -> bytes:
    return b"\r\n" if b"\r\n" in content else b"\n"


def definition_checksum(
    *,
    manifest: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
    mechanics: Sequence[Mapping[str, Any]],
) -> str:
    """Pinned v1 algorithm used by sagasmith-dnd for native definitions."""

    def native_records(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                key: copy.deepcopy(value)
                for key, value in dict(item).items()
                if key != "rule_definition_id"
            }
            for item in items
        ]

    encoded = json.dumps(
        {
            "manifest": copy.deepcopy(dict(manifest)),
            "artifacts": native_records(artifacts),
            "mechanics": native_records(mechanics),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def recompute_definition_checksums(package: dict[str, Any]) -> list[dict[str, Any]]:
    """Refresh every definition from its exact manifest/artifact/mechanic inputs."""

    content = dict(package.get("content") or {})
    artifacts = list(content.get("artifacts") or [])
    mechanics = list(content.get("mechanics") or [])
    definitions = list(content.get("rule_definitions") or [])
    changes = []
    for definition in definitions:
        definition_id = str(definition["id"])
        matching_artifacts = [
            item
            for item in artifacts
            if str(item.get("rule_definition_id") or "") == definition_id
        ]
        matching_mechanics = [
            item
            for item in mechanics
            if str(item.get("rule_definition_id") or "") == definition_id
        ]
        checksum = definition_checksum(
            manifest=definition["manifest"],
            artifacts=matching_artifacts,
            mechanics=matching_mechanics,
        )
        changes.append(
            {
                "id": definition_id,
                "source_definition_checksum": str(definition["definition_checksum"]),
                "definition_checksum": checksum,
                "artifact_count": len(matching_artifacts),
                "mechanic_count": len(matching_mechanics),
            }
        )
        definition["definition_checksum"] = checksum
    content["rule_definitions"] = definitions
    package["content"] = content
    return changes


def _correct_package(package: dict[str, Any]) -> dict[str, Any]:
    from sagasmith_core.content_pack import build_content_package
    from sagasmith_dnd.content_packages import (
        content_definition_checksum,
        validate_dnd_content_package,
    )

    if (
        package.get("id") != PACKAGE_ID
        or package.get("version") != SOURCE_VERSION
        or package.get("checksum") != SOURCE_CHECKSUM
    ):
        raise PublicationConflictError("SCAG source identity is not finalized 1.0.3")
    corrected = copy.deepcopy(package)
    changes = recompute_definition_checksums(corrected)
    if len(changes) != 1 or changes[0] != {
        "id": DEFINITION_ID,
        "source_definition_checksum": SOURCE_DEFINITION_CHECKSUM,
        "definition_checksum": TARGET_DEFINITION_CHECKSUM,
        "artifact_count": 108,
        "mechanic_count": 0,
    }:
        raise PublicationConflictError("SCAG definition inputs changed unexpectedly")
    definition = corrected["content"]["rule_definitions"][0]
    artifacts = corrected["content"]["artifacts"]
    mechanics = corrected["content"]["mechanics"]
    runtime_checksum = content_definition_checksum(
        manifest=definition["manifest"],
        artifacts=artifacts,
        mechanics=mechanics,
    )
    if runtime_checksum != TARGET_DEFINITION_CHECKSUM:
        raise PublicationConflictError(
            "sagasmith-dnd checksum algorithm drifted from v1"
        )
    metadata = copy.deepcopy(corrected["metadata"])
    metadata["definition_checksum_correction"] = {
        "schema": "sagasmith.pack-definition-checksum-correction.v1",
        "algorithm": "sagasmith-dnd.content-definition-checksum.v1",
        "source_version": SOURCE_VERSION,
        "source_checksum": SOURCE_CHECKSUM,
        "updated_on": PUBLISHED_ON,
        "definitions": changes,
    }
    rebuilt = build_content_package(
        kind=str(corrected["kind"]),
        package_id=PACKAGE_ID,
        version=TARGET_VERSION,
        system_id=str(corrected["system_id"]),
        manifest=corrected["manifest"],
        dependencies=corrected["dependencies"],
        sources=corrected["sources"],
        assets=corrected["assets"],
        content_reviews=corrected["content_reviews"],
        actors=corrected["actors"],
        content=corrected["content"],
        metadata=metadata,
    )
    return validate_dnd_content_package(rebuilt)


def _source_entry() -> dict[str, Any]:
    return {
        "system_id": "dnd5e",
        "kind": "addon",
        "id": PACKAGE_ID,
        "action": "source_corrected_current",
        "source_version": "1.0.2",
        "source_checksum": PRIOR_ARCHIVES[1]["checksum"],
        "version": SOURCE_VERSION,
        "checksum": SOURCE_CHECKSUM,
        "archive_sha256": SOURCE_ARCHIVE_SHA256,
        "archive_size": SOURCE_ARCHIVE_SIZE,
        "source_path": PRIOR_ARCHIVES[1]["path"],
        "path": SOURCE_PATH,
        "dependencies": [],
        "provided_rule_definitions": [{"id": DEFINITION_ID, "version": "1.0.0"}],
        "runtime_rule_dependencies": [copy.deepcopy(RUNTIME_DEPENDENCY)],
    }


def _target_entry() -> dict[str, Any]:
    entry = _source_entry()
    entry.update(
        {
            "action": "definition_checksum_corrected_current",
            "source_version": SOURCE_VERSION,
            "source_checksum": SOURCE_CHECKSUM,
            "version": TARGET_VERSION,
            "checksum": TARGET_CHECKSUM,
            "archive_sha256": TARGET_ARCHIVE_SHA256,
            "archive_size": TARGET_ARCHIVE_SIZE,
            "source_path": SOURCE_PATH,
            "path": TARGET_PATH,
        }
    )
    return entry


def _retained_entry(archive: Mapping[str, Any], *, target: bool) -> dict[str, Any]:
    return {
        "identity": ["dnd5e", "addon", PACKAGE_ID],
        "version": archive["version"],
        "checksum": archive["checksum"],
        "path": archive["path"],
        "archive_sha256": archive["archive_sha256"],
        "archive_size": archive["archive_size"],
        "retained_finalized": True,
        "superseded_by": {
            "version": TARGET_VERSION if target else SOURCE_VERSION,
            "checksum": TARGET_CHECKSUM if target else SOURCE_CHECKSUM,
        },
    }


def _source_archive_record() -> dict[str, Any]:
    return {
        "version": SOURCE_VERSION,
        "checksum": SOURCE_CHECKSUM,
        "path": SOURCE_PATH,
        "archive_sha256": SOURCE_ARCHIVE_SHA256,
        "archive_size": SOURCE_ARCHIVE_SIZE,
    }


def _source_evidence() -> dict[str, Any]:
    return {
        "id": PACKAGE_ID,
        "kind": "addon",
        "checksum": SOURCE_CHECKSUM,
        "campaign_id": "ef2d80f8-fa9b-466a-839b-92f4481c416f",
        "idempotent_replay": True,
        "listed_count": 1,
    }


def _target_evidence() -> dict[str, Any]:
    value = _source_evidence()
    value["checksum"] = TARGET_CHECKSUM
    return value


def _is_scag_retained(item: object) -> bool:
    return (
        isinstance(item, dict)
        and list(item.get("identity") or [None, None, None])[2] == PACKAGE_ID
    )


def _is_reparse_point(path: Path) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if is_junction is not None and is_junction():
            return True
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except OSError as error:
        raise PublicationConflictError(f"cannot verify path safety: {path}") from error


def _safe_package_root(root: Path) -> Path:
    lexical = root / "packages"
    if _is_reparse_point(lexical):
        raise PublicationConflictError("packages/ must not be a link or reparse point")
    if not lexical.is_dir():
        raise PublicationConflictError("packages/ must be a real directory")
    resolved = lexical.resolve()
    if resolved != lexical or resolved.parent != root:
        raise PublicationConflictError(
            "packages/ resolves outside content-library root"
        )
    return resolved


def _safe_archive_path(root: Path, relative: object) -> Path:
    text = str(relative)
    if "\\" in text or Path(text).is_absolute():
        raise PublicationConflictError(f"unsafe archive path: {text!r}")
    parts = text.split("/")
    if len(parts) != 2 or parts[0] != "packages" or parts[1] in {"", ".", ".."}:
        raise PublicationConflictError(f"unsafe archive path: {text!r}")
    package_root = _safe_package_root(root)
    lexical = root / text
    if _is_reparse_point(lexical):
        raise PublicationConflictError(f"archive must not be a link: {text!r}")
    resolved = lexical.resolve()
    if not resolved.is_relative_to(root) or resolved.parent != package_root:
        raise PublicationConflictError(f"archive path escapes packages/: {text!r}")
    return resolved


def _scag_entry(values: object, *, field: str) -> dict[str, Any]:
    if not isinstance(values, list):
        raise PublicationConflictError(f"{field} must be a list")
    matches = [
        item
        for item in values
        if isinstance(item, dict) and item.get("id") == PACKAGE_ID
    ]
    if len(matches) != 1 or matches[0] not in (_source_entry(), _target_entry()):
        raise PublicationConflictError(f"{field} SCAG metadata conflicts")
    return matches[0]


def _validate_paths(root: Path, index: dict[str, Any], report: dict[str, Any]) -> None:
    for item in [
        *list(index.get("packages") or []),
        *list(report.get("packages") or []),
    ]:
        if not isinstance(item, dict):
            raise PublicationConflictError("package metadata must contain objects")
        _safe_archive_path(root, item.get("path"))
    for item in list(report.get("superseded_archives") or []):
        if isinstance(item, dict) and item.get("retained_finalized") is True:
            _safe_archive_path(root, item.get("path"))


def _desired_metadata(
    root: Path,
    index: dict[str, Any],
    report: dict[str, Any],
    summary: dict[str, Any],
    evidence: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    _validate_paths(root, index, report)
    _scag_entry(index.get("packages"), field="index.packages")
    _scag_entry(report.get("packages"), field="migration-report.packages")
    index_other = [item for item in index["packages"] if item.get("id") != PACKAGE_ID]
    report_other = [item for item in report["packages"] if item.get("id") != PACKAGE_ID]
    if index_other != report_other:
        raise PublicationConflictError("index/report non-SCAG metadata differs")

    retained = report.get("superseded_archives")
    if not isinstance(retained, list):
        raise PublicationConflictError("superseded_archives must be a list")
    scag_retained = [item for item in retained if _is_scag_retained(item)]
    source_retained = [_retained_entry(item, target=False) for item in PRIOR_ARCHIVES]
    target_retained = [
        *[_retained_entry(item, target=True) for item in PRIOR_ARCHIVES],
        _retained_entry(_source_archive_record(), target=True),
    ]
    if scag_retained not in (source_retained, target_retained):
        raise PublicationConflictError("SCAG retained archive metadata conflicts")
    counts = report.get("counts")
    if not isinstance(counts, dict) or counts.get("superseded_archives") != len(
        retained
    ):
        raise PublicationConflictError("superseded archive count conflicts")

    dnd_evidence = evidence.get("dnd")
    if not isinstance(dnd_evidence, list):
        raise PublicationConflictError("D&D import evidence must be a list")
    evidence_matches = [item for item in dnd_evidence if item.get("id") == PACKAGE_ID]
    if len(evidence_matches) != 1 or evidence_matches[0] not in (
        _source_evidence(),
        _target_evidence(),
    ):
        raise PublicationConflictError("SCAG import evidence conflicts")

    desired_index = copy.deepcopy(index)
    desired_index["generated_on"] = PUBLISHED_ON
    desired_index["packages"] = [
        _target_entry() if item.get("id") == PACKAGE_ID else item
        for item in desired_index["packages"]
    ]
    desired_report = copy.deepcopy(report)
    desired_report["generated_on"] = PUBLISHED_ON
    desired_report["packages"] = copy.deepcopy(desired_index["packages"])
    desired_retained = []
    source_added = False
    for item in retained:
        if not _is_scag_retained(item):
            desired_retained.append(item)
            continue
        if item.get("version") == SOURCE_VERSION:
            source_added = True
            archive = _source_archive_record()
        else:
            archive = next(
                prior
                for prior in PRIOR_ARCHIVES
                if prior["version"] == item.get("version")
            )
        desired_retained.append(_retained_entry(archive, target=True))
    if not source_added:
        desired_retained.append(_retained_entry(_source_archive_record(), target=True))
    desired_report["superseded_archives"] = desired_retained
    desired_report["counts"]["superseded_archives"] = len(desired_retained)

    archive_validation = summary.get("archive_validation")
    if not isinstance(archive_validation, dict):
        raise PublicationConflictError("archive validation summary must be an object")
    metric_keys = {
        "bytes",
        "retained_superseded_archives",
        "retained_superseded_bytes",
        "stored_archives",
        "stored_bytes",
    }
    actual_metrics = {key: archive_validation.get(key) for key in metric_keys}
    source_metrics = {
        "bytes": 1062814386,
        "retained_superseded_archives": 2,
        "retained_superseded_bytes": 1810551,
        "stored_archives": 48,
        "stored_bytes": 1064624937,
    }
    target_metrics = {
        "bytes": 1062814544,
        "retained_superseded_archives": 3,
        "retained_superseded_bytes": 2716199,
        "stored_archives": 49,
        "stored_bytes": 1065530743,
    }
    if actual_metrics not in (source_metrics, target_metrics):
        raise PublicationConflictError("validation summary archive metrics conflict")
    desired_summary = copy.deepcopy(summary)
    desired_summary["archive_validation"].update(target_metrics)
    desired_evidence = copy.deepcopy(evidence)
    desired_evidence["dnd"] = [
        _target_evidence() if item.get("id") == PACKAGE_ID else item
        for item in desired_evidence["dnd"]
    ]
    return desired_index, desired_report, desired_summary, desired_evidence


def _build_target_archive(source_bytes: bytes) -> bytes:
    from sagasmith_core.content_pack import dumps_content_archive, loads_content_archive

    package, blobs = loads_content_archive(source_bytes)
    rebuilt = _correct_package(package)
    if rebuilt.get("checksum") != TARGET_CHECKSUM:
        raise PublicationConflictError("rebuilt SCAG package checksum changed")
    return dumps_content_archive(rebuilt, blobs)


def _atomic_replace(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def publish(
    *,
    root: Path = ROOT,
    archive_builder: Callable[[bytes], bytes] | None = None,
    fail_after_replace: int | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise PublicationConflictError("content-library root must exist")
    _safe_package_root(root)
    paths = {
        "index": root / "index.json",
        "report": root / "migration-report.json",
        "summary": root / "validation-summary.json",
        "evidence": root / "import-evidence.json",
    }
    for path in paths.values():
        if path.resolve().parent != root or not path.is_file():
            raise PublicationConflictError(f"unsafe or missing metadata: {path.name}")
    metadata_bytes = {name: path.read_bytes() for name, path in paths.items()}
    index = _read_object(paths["index"])
    report = _read_object(paths["report"])
    summary = _read_object(paths["summary"])
    evidence = _read_object(paths["evidence"])
    desired = _desired_metadata(root, index, report, summary, evidence)
    desired_objects = dict(zip(paths, desired, strict=True))

    source_path = _safe_archive_path(root, SOURCE_PATH)
    target_path = _safe_archive_path(root, TARGET_PATH)
    if not source_path.is_file():
        raise PublicationConflictError("finalized SCAG 1.0.3 source archive is missing")
    source_bytes = source_path.read_bytes()
    if (
        len(source_bytes) != SOURCE_ARCHIVE_SIZE
        or hashlib.sha256(source_bytes).hexdigest() != SOURCE_ARCHIVE_SHA256
    ):
        raise PublicationConflictError("finalized SCAG 1.0.3 source archive conflicts")
    target_bytes = target_path.read_bytes() if target_path.exists() else None
    if target_bytes is not None and (
        len(target_bytes) != TARGET_ARCHIVE_SIZE
        or hashlib.sha256(target_bytes).hexdigest() != TARGET_ARCHIVE_SHA256
    ):
        raise PublicationConflictError("SCAG 1.0.4 target archive conflicts")
    if target_bytes is None:
        target_bytes = (archive_builder or _build_target_archive)(source_bytes)
        if (
            len(target_bytes) != TARGET_ARCHIVE_SIZE
            or hashlib.sha256(target_bytes).hexdigest() != TARGET_ARCHIVE_SHA256
        ):
            raise PublicationConflictError("rebuilt SCAG 1.0.4 archive conflicts")

    desired_files = [(target_path, target_bytes)]
    current_objects = {
        "index": index,
        "report": report,
        "summary": summary,
        "evidence": evidence,
    }
    for name, path in paths.items():
        content = (
            metadata_bytes[name]
            if current_objects[name] == desired_objects[name]
            else _object_bytes(
                desired_objects[name], newline=_newline_for(metadata_bytes[name])
            )
        )
        desired_files.append((path, content))
    writes = 0
    for path, content in desired_files:
        if path.exists() and path.read_bytes() == content:
            continue
        _atomic_replace(path, content)
        writes += 1
        if fail_after_replace == writes:
            raise InjectedPublicationFailure(f"failure after replacement {writes}")
    return {
        "id": PACKAGE_ID,
        "version": TARGET_VERSION,
        "checksum": TARGET_CHECKSUM,
        "definition_checksum": TARGET_DEFINITION_CHECKSUM,
        "status": "already_current" if writes == 0 else "published",
        "writes": writes,
    }


def main() -> None:
    print(json.dumps(publish()))


if __name__ == "__main__":
    main()
