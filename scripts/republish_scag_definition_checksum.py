"""Repair an authorized local SCAG archive without publishing a content library.

Requires explicit source/output paths. The input archive is immutable, the output
must be outside this repository, and no catalog or runtime import evidence changes.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

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


class PublicationConflictError(RuntimeError):
    """Raised before writes when a path or archive identity conflicts."""


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


def _build_target_archive(source_bytes: bytes) -> bytes:
    from sagasmith_core.content_pack import dumps_content_archive, loads_content_archive

    package, blobs = loads_content_archive(source_bytes)
    rebuilt = _correct_package(package)
    if rebuilt.get("checksum") != TARGET_CHECKSUM:
        raise PublicationConflictError("rebuilt SCAG package checksum changed")
    return dumps_content_archive(rebuilt, blobs)


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


def _unlinked_path(path: Path) -> Path:
    if ".." in path.parts:
        raise PublicationConflictError("parent traversal is not accepted")
    absolute = path.absolute()
    for component in (absolute, *absolute.parents):
        if _is_reparse_point(component):
            raise PublicationConflictError(
                "paths must not contain links or reparse points"
            )
    return absolute


def repair_local_archive(*, source: Path, output: Path) -> dict[str, Any]:
    """Repair one authorized local copy; never publish or rewrite library evidence."""
    source = _unlinked_path(source)
    output = _unlinked_path(output)
    repository = Path(__file__).resolve().parents[1]
    if output.is_relative_to(repository):
        raise PublicationConflictError("output must be outside this repository")
    if output == source:
        raise PublicationConflictError("source archive is immutable")
    if not source.is_file() or not output.parent.is_dir():
        raise PublicationConflictError("source file and output directory must exist")
    source_bytes = source.read_bytes()
    if (
        len(source_bytes) != SOURCE_ARCHIVE_SIZE
        or hashlib.sha256(source_bytes).hexdigest() != SOURCE_ARCHIVE_SHA256
    ):
        raise PublicationConflictError(
            "source is not the exact finalized SCAG 1.0.3 archive"
        )
    target_bytes = _build_target_archive(source_bytes)
    if (
        len(target_bytes) != TARGET_ARCHIVE_SIZE
        or hashlib.sha256(target_bytes).hexdigest() != TARGET_ARCHIVE_SHA256
    ):
        raise PublicationConflictError("rebuilt SCAG 1.0.4 archive conflicts")
    status = "already_present"
    if output.exists():
        if not output.is_file() or output.read_bytes() != target_bytes:
            raise PublicationConflictError("output exists with different content")
    else:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=output.parent, prefix=".scag-repair-", suffix=".tmp"
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(target_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            # An exclusive link publishes the complete file without ever replacing
            # a concurrent destination. Unsupported filesystems fail closed.
            _unlinked_path(output)
            os.link(temporary, output)
            status = "created"
        finally:
            temporary.unlink(missing_ok=True)
    return {
        "id": PACKAGE_ID,
        "version": TARGET_VERSION,
        "checksum": TARGET_CHECKSUM,
        "definition_checksum": TARGET_DEFINITION_CHECKSUM,
        "archive_sha256": TARGET_ARCHIVE_SHA256,
        "status": status,
        "published": False,
        "import_verified": False,
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(repair_local_archive(source=args.source, output=args.output)))


if __name__ == "__main__":
    main()
