"""Publish the immutable SCAG City Watch and Investigator integrity correction."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1] / "content-library"
PACKAGE_ID = (
    "dnd5e.addon.rulebook.d-d-5e-sword-coast-adventurer-s-guide.16e6a243ef0a.addon"
)
SOURCE_VERSION = "1.0.2"
SOURCE_CHECKSUM = "5e5504ec3d2ebb82e548a48c6b97f49938ed9d08bf94d6efaa08600a11ab3c22"
SOURCE_ARCHIVE_SHA256 = (
    "63546d562fb921391202e10232733d45e818c71ed1d6cbdd164c11b1fb82359d"
)
SOURCE_ARCHIVE_SIZE = 905484
TARGET_VERSION = "1.0.3"
TARGET_CHECKSUM = "ff8bbff7268d3e9afab5fce2d2ae320422e9d64523c6d2c1c327689dae59a9d9"
TARGET_ARCHIVE_SHA256 = (
    "1bb977b1a54f9aeb6f31413d7e8918294f2f38a353c48597287ed6ef3d111d2a"
)
TARGET_ARCHIVE_SIZE = 905648
PUBLISHED_ON = "2026-09-01"
CITY_WATCH_SUFFIX = ".background.city-watch"
INVESTIGATOR_SUFFIX = ".background.investigator"
SECTION_TITLES = {
    "city_watch": "CITY WATCH",
    "watchers_eye": "FEATURE : WATCHER'S EYE",
    "investigator": "VARIANT: INVESTIGATOR",
}
SRD_ITEM_IDS = {
    "Horn": "dnd5e.content.srd2014.item.horn",
    "Manacles": "dnd5e.content.srd2014.item.manacles",
    "Pouch": "dnd5e.content.srd2014.item.pouch",
}
SOURCE_PATH = (
    "packages/5e5504ec3d2e-dnd5e.addon.rulebook."
    "d-d-5e-sword-coast-adventurer-s-guide.16e6a243ef0a.addon-1.0.2.sagasmith-pack"
)
TARGET_PATH = (
    "packages/ff8bbff7268d-dnd5e.addon.rulebook."
    "d-d-5e-sword-coast-adventurer-s-guide.16e6a243ef0a.addon-1.0.3.sagasmith-pack"
)
PREVIOUS_PATH = (
    "packages/efbba0006ef8-dnd5e.addon.rulebook."
    "d-d-5e-sword-coast-adventurer-s-guide.16e6a243ef0a.addon-1.0.1.sagasmith-pack"
)
PREVIOUS_VERSION = "1.0.1"
PREVIOUS_CHECKSUM = "efbba0006ef837961a3d87203c60a49b1ed57428cdb10999aa8b6378964a5bb9"
PREVIOUS_ARCHIVE_SHA256 = (
    "d7e755e914f94871b0bf59966109e84f0ae2302776be9127bb558971d8d125d3"
)
PREVIOUS_ARCHIVE_SIZE = 905067
RULE_DEFINITION_ID = PACKAGE_ID.removesuffix(".addon")
RUNTIME_DEPENDENCY = {
    "checksum": "3f7508a4177c3dd4a9678d55d55d67a48c282a17f03a0943e092de486f850670",
    "id": "dnd5e.content.srd2014",
    "version": "1.24.0",
}


class PublicationConflictError(RuntimeError):
    """Raised before writes when a source, target, or metadata identity conflicts."""


class InjectedPublicationFailure(RuntimeError):
    """Test-only crash injected immediately after an atomic replacement."""


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _object_bytes(value: dict[str, Any], *, newline: bytes) -> bytes:
    content = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return content.replace(b"\n", newline)


def _newline_for(content: bytes) -> bytes:
    return b"\r\n" if b"\r\n" in content else b"\n"


def _one(values: list[dict[str, Any]], *, suffix: str) -> dict[str, Any]:
    matches = [value for value in values if str(value.get("id") or "").endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one artifact ending with {suffix!r}")
    return matches[0]


def _source_sections(
    package: dict[str, Any], blobs: dict[str, bytes]
) -> tuple[dict[str, Any], dict[str, tuple[dict[str, Any], dict[str, Any], str]]]:
    sources = list(package.get("sources") or [])
    if len(sources) != 1:
        raise ValueError("SCAG Pack must expose exactly one indexed source")
    source = sources[0]
    sections = list(source.get("sections") or [])
    asset_key = str(source.get("normalized_document_asset_key") or "")
    assets = [
        asset
        for asset in package.get("assets") or []
        if asset.get("asset_key") == asset_key
    ]
    if len(assets) != 1:
        raise ValueError("SCAG normalized source asset is missing or ambiguous")
    normalized = blobs[str(assets[0]["checksum"])].decode("utf-8")
    result: dict[str, tuple[dict[str, Any], dict[str, Any], str]] = {}
    for key, title in SECTION_TITLES.items():
        matches = [
            section
            for section in sections
            if str(section.get("title") or "").strip().upper() == title
        ]
        if len(matches) != 1:
            raise ValueError(f"SCAG source must expose exactly one {title} section")
        section = matches[0]
        chunks = list(section.get("chunks") or [])
        if len(chunks) != 1:
            raise ValueError(f"{title} must map to exactly one source chunk")
        text = normalized[int(section["start_offset"]) : int(section["end_offset"])]
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != section.get(
            "content_hash"
        ):
            raise ValueError(f"{title} source offsets do not match the indexed hash")
        result[key] = (section, chunks[0], text.strip())
    city_ordinal = result["city_watch"][0]["ordinal"]
    if result["watchers_eye"][0].get("parent_ordinal") != city_ordinal:
        raise ValueError("Watcher's Eye must remain a child of City Watch")
    if result["investigator"][0].get("parent_ordinal") != city_ordinal:
        raise ValueError("Investigator must remain a variant of City Watch")
    return source, result


def _source_citation(
    source_key: str, chunk: dict[str, Any], text: str
) -> dict[str, Any]:
    return {
        "source": f"rule-source:{source_key}",
        "source_excerpt": text,
        "source_ref": {"chunk_key": str(chunk["key"])},
    }


def _source_ref(source_key: str, chunk: dict[str, Any], *, note: str) -> dict[str, Any]:
    return {
        "chunk_key": str(chunk["key"]),
        "note": note,
        "page": int(chunk["page_start"]),
        "source_key": source_key,
    }


def _review_artifact(artifact: dict[str, Any], *, references: list[str]) -> None:
    from sagasmith_dnd.content_validation import (
        build_catalog_review,
        build_selection_contract,
    )

    old_contract = dict(artifact["selection_contract"])
    artifact["selection_contract"] = build_selection_contract(
        artifact,
        status=str(old_contract["status"]),
        materializer=str(old_contract["materializer"]),
        references=references,
        blockers=list(old_contract["blockers"]),
    )
    decisions = copy.deepcopy(artifact["catalog_review"]["decisions"])
    artifact["catalog_review"] = build_catalog_review(
        artifact,
        decisions=decisions,
        status="approved",
    )


def _correct_package(
    package: dict[str, Any], blobs: dict[str, bytes]
) -> dict[str, Any]:
    from sagasmith_core.content_pack import build_content_package
    from sagasmith_dnd.content_packages import validate_dnd_content_package

    if (
        package.get("id") != PACKAGE_ID
        or package.get("version") != SOURCE_VERSION
        or package.get("checksum") != SOURCE_CHECKSUM
    ):
        raise ValueError("SCAG source Pack identity is not the reviewed 1.0.2 archive")
    corrected = copy.deepcopy(package)
    source, sections = _source_sections(corrected, blobs)
    source_key = str(source["source_key"])
    artifacts = list(corrected["content"]["artifacts"])
    city_watch = _one(artifacts, suffix=CITY_WATCH_SUFFIX)
    investigator = _one(artifacts, suffix=INVESTIGATOR_SUFFIX)

    city_equipment = dict(city_watch["card"]["background_grants"]["equipment"])
    old_items = list(city_equipment.get("items") or [])
    if len(old_items) != 3:
        raise ValueError(
            "City Watch 1.0.2 must contain the reviewed three-item projection"
        )
    uniform = copy.deepcopy(old_items[0])
    if dict(uniform.get("inventory_template") or {}).get("name") != "Watch Uniform":
        raise ValueError("City Watch uniform projection changed unexpectedly")
    city_equipment["items"] = [
        uniform,
        *[
            {"artifact_id": artifact_id, "quantity": 1}
            for artifact_id in SRD_ITEM_IDS.values()
        ],
    ]
    city_watch["card"]["background_grants"]["equipment"] = city_equipment
    _review_artifact(
        city_watch,
        references=list(city_watch["selection_contract"]["references"]),
    )

    city_section, city_chunk, city_text = sections["city_watch"]
    feature_section, feature_chunk, feature_text = sections["watchers_eye"]
    variant_section, variant_chunk, variant_text = sections["investigator"]
    del city_section, feature_section, variant_section
    base_description = str(city_watch["card"]["description"])
    if city_text not in base_description or feature_text not in base_description:
        raise ValueError(
            "City Watch 1.0.2 does not retain its complete reviewed source text"
        )
    investigator["card"]["description"] = (
        f"{base_description} Variant: Investigator {variant_text}"
    )
    investigator["card"]["skill_proficiencies"] = ["Investigation", "Insight"]
    investigator_grants = copy.deepcopy(city_watch["card"]["background_grants"])
    investigator_grants["skills"] = ["Investigation", "Insight"]
    investigator["card"]["background_grants"] = investigator_grants
    investigator_rulings = list(investigator["card"].get("ruling_requirements") or [])
    if len(investigator_rulings) != 1:
        raise ValueError("Investigator must retain one source-bound ruling boundary")
    investigator_rulings[0]["source_excerpt"] = (
        f"{city_text} Feature: Watcher's Eye {feature_text} "
        f"Variant: Investigator {variant_text}"
    )
    clauses = list(investigator.get("rule_clauses") or [])
    if len(clauses) != 1:
        raise ValueError("Investigator must retain one narrative ruling clause")
    clauses[0]["source_citations"] = [
        _source_citation(source_key, city_chunk, city_text),
        _source_citation(source_key, feature_chunk, feature_text),
        _source_citation(source_key, variant_chunk, variant_text),
    ]
    investigator["rule_refs"] = [
        f"rule-source:{source_key}#chunk:{chunk['key']}"
        for chunk in (city_chunk, feature_chunk, variant_chunk)
    ]
    investigator["source_refs"] = [
        _source_ref(
            source_key, city_chunk, note="Inherited City Watch background evidence"
        ),
        _source_ref(
            source_key,
            feature_chunk,
            note="Inherited Watcher's Eye feature evidence",
        ),
        _source_ref(source_key, variant_chunk, note="Investigator variant evidence"),
    ]
    _review_artifact(
        investigator,
        references=[
            f"rule-source-chunk:{chunk['key']}"
            for chunk in (city_chunk, feature_chunk, variant_chunk)
        ],
    )

    metadata = copy.deepcopy(corrected["metadata"])
    metadata["source_correction"] = {
        "schema": "sagasmith.pack-source-correction.v1",
        "source_version": SOURCE_VERSION,
        "source_checksum": SOURCE_CHECKSUM,
        "updated_on": PUBLISHED_ON,
        "changes": [
            "completed the City Watch equipment projection with the reviewed pouch",
            "bound Horn, Manacles, and Pouch to their pinned SRD 2014 item identities",
            "completed Investigator inheritance from City Watch and Watcher's Eye",
            "preserved the exact Investigator skill replacement",
        ],
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
        "source_version": PREVIOUS_VERSION,
        "source_checksum": PREVIOUS_CHECKSUM,
        "version": SOURCE_VERSION,
        "checksum": SOURCE_CHECKSUM,
        "archive_sha256": SOURCE_ARCHIVE_SHA256,
        "archive_size": SOURCE_ARCHIVE_SIZE,
        "source_path": PREVIOUS_PATH,
        "path": SOURCE_PATH,
        "dependencies": [],
        "provided_rule_definitions": [{"id": RULE_DEFINITION_ID, "version": "1.0.0"}],
        "runtime_rule_dependencies": [copy.deepcopy(RUNTIME_DEPENDENCY)],
    }


def _target_entry() -> dict[str, Any]:
    entry = _source_entry()
    entry.update(
        {
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


def _previous_retained(*, target: bool) -> dict[str, Any]:
    return {
        "identity": ["dnd5e", "addon", PACKAGE_ID],
        "version": PREVIOUS_VERSION,
        "checksum": PREVIOUS_CHECKSUM,
        "path": PREVIOUS_PATH,
        "archive_sha256": PREVIOUS_ARCHIVE_SHA256,
        "archive_size": PREVIOUS_ARCHIVE_SIZE,
        "retained_finalized": True,
        "superseded_by": {
            "version": TARGET_VERSION if target else SOURCE_VERSION,
            "checksum": TARGET_CHECKSUM if target else SOURCE_CHECKSUM,
        },
    }


def _source_retained() -> dict[str, Any]:
    return {
        "identity": ["dnd5e", "addon", PACKAGE_ID],
        "version": SOURCE_VERSION,
        "checksum": SOURCE_CHECKSUM,
        "path": SOURCE_PATH,
        "archive_sha256": SOURCE_ARCHIVE_SHA256,
        "archive_size": SOURCE_ARCHIVE_SIZE,
        "retained_finalized": True,
        "superseded_by": {
            "version": TARGET_VERSION,
            "checksum": TARGET_CHECKSUM,
        },
    }


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
        raise PublicationConflictError(
            f"cannot verify path for links or reparse points: {path}"
        ) from error


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
    path = lexical.resolve()
    if not path.is_relative_to(root) or path.parent != package_root:
        raise PublicationConflictError(f"archive path escapes packages/: {text!r}")
    return path


def _validate_metadata_paths(
    root: Path, index: dict[str, Any], report: dict[str, Any]
) -> None:
    for item in list(index.get("packages") or []):
        _safe_archive_path(root, item.get("path"))
    for item in list(report.get("packages") or []):
        _safe_archive_path(root, item.get("path"))
    for item in list(report.get("superseded_archives") or []):
        if item.get("retained_finalized") is True:
            _safe_archive_path(root, item.get("path"))


def _scag_entry(values: object, *, field: str) -> dict[str, Any]:
    if not isinstance(values, list):
        raise PublicationConflictError(f"{field} must be a list")
    matches = [
        item
        for item in values
        if isinstance(item, dict) and item.get("id") == PACKAGE_ID
    ]
    if len(matches) != 1:
        raise PublicationConflictError(f"{field} must contain exactly one SCAG Pack")
    entry = matches[0]
    if entry not in (_source_entry(), _target_entry()):
        raise PublicationConflictError(
            f"{field} SCAG metadata conflicts with 1.0.2/1.0.3"
        )
    return entry


def _is_scag_retained(item: object) -> bool:
    return (
        isinstance(item, dict)
        and list(item.get("identity") or [None, None, None])[2] == PACKAGE_ID
    )


def _desired_metadata(
    root: Path,
    index: dict[str, Any],
    report: dict[str, Any],
    summary: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    _validate_metadata_paths(root, index, report)
    _scag_entry(index.get("packages"), field="index.packages")
    _scag_entry(report.get("packages"), field="migration-report.packages")

    index_other = [item for item in index["packages"] if item.get("id") != PACKAGE_ID]
    report_other = [item for item in report["packages"] if item.get("id") != PACKAGE_ID]
    if index_other != report_other:
        raise PublicationConflictError("index/report non-SCAG package metadata differs")

    retained = report.get("superseded_archives")
    if not isinstance(retained, list):
        raise PublicationConflictError(
            "migration-report.superseded_archives must be a list"
        )
    scag_retained = [item for item in retained if _is_scag_retained(item)]
    old_retained = [_previous_retained(target=False)]
    target_retained = [_previous_retained(target=True), _source_retained()]
    if scag_retained not in (old_retained, target_retained):
        raise PublicationConflictError("SCAG retained archive metadata conflicts")

    counts = report.get("counts")
    if not isinstance(counts, dict):
        raise PublicationConflictError("migration-report.counts must be an object")
    expected_count = len(retained)
    if counts.get("superseded_archives") != expected_count:
        raise PublicationConflictError("superseded archive count conflicts with report")

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
        elif item.get("version") == PREVIOUS_VERSION:
            desired_retained.append(_previous_retained(target=True))
        elif item.get("version") == SOURCE_VERSION:
            desired_retained.append(_source_retained())
            source_added = True
    if not source_added:
        desired_retained.append(_source_retained())
    desired_report["superseded_archives"] = desired_retained
    desired_report["counts"]["superseded_archives"] = len(desired_retained)

    archive_validation = summary.get("archive_validation")
    if not isinstance(archive_validation, dict):
        raise PublicationConflictError(
            "validation-summary.archive_validation must be an object"
        )
    metric_keys = {
        "bytes",
        "retained_superseded_archives",
        "retained_superseded_bytes",
        "stored_archives",
        "stored_bytes",
    }
    actual_metrics = {key: archive_validation.get(key) for key in metric_keys}
    source_metrics = {
        "bytes": 1062814222,
        "retained_superseded_archives": 1,
        "retained_superseded_bytes": PREVIOUS_ARCHIVE_SIZE,
        "stored_archives": 47,
        "stored_bytes": 1063719289,
    }
    target_metrics = {
        "bytes": 1062814386,
        "retained_superseded_archives": 2,
        "retained_superseded_bytes": PREVIOUS_ARCHIVE_SIZE + SOURCE_ARCHIVE_SIZE,
        "stored_archives": 48,
        "stored_bytes": 1064624937,
    }
    if actual_metrics not in (source_metrics, target_metrics):
        raise PublicationConflictError("validation summary archive metrics conflict")

    desired_summary = copy.deepcopy(summary)
    desired_summary["archive_validation"].update(target_metrics)
    return desired_index, desired_report, desired_summary


def _build_target_archive(source_bytes: bytes) -> bytes:
    from sagasmith_core.content_pack import dumps_content_archive, loads_content_archive

    package, blobs = loads_content_archive(source_bytes)
    rebuilt = _correct_package(package, blobs)
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
    index_path = root / "index.json"
    report_path = root / "migration-report.json"
    summary_path = root / "validation-summary.json"
    for path in (index_path, report_path, summary_path):
        if path.resolve().parent != root or not path.is_file():
            raise PublicationConflictError(
                f"required metadata file is unsafe or missing: {path.name}"
            )

    metadata_bytes = {
        path: path.read_bytes() for path in (index_path, report_path, summary_path)
    }
    index = _read_object(index_path)
    report = _read_object(report_path)
    summary = _read_object(summary_path)
    desired_index, desired_report, desired_summary = _desired_metadata(
        root, index, report, summary
    )

    source_path = _safe_archive_path(root, SOURCE_PATH)
    target_path = _safe_archive_path(root, TARGET_PATH)
    if not source_path.is_file():
        raise PublicationConflictError("reviewed SCAG 1.0.2 source archive is missing")
    source_bytes = source_path.read_bytes()
    if (
        len(source_bytes) != SOURCE_ARCHIVE_SIZE
        or hashlib.sha256(source_bytes).hexdigest() != SOURCE_ARCHIVE_SHA256
    ):
        raise PublicationConflictError("reviewed SCAG 1.0.2 source archive conflicts")

    target_exists = target_path.exists()
    if target_exists and not target_path.is_file():
        raise PublicationConflictError("SCAG 1.0.3 target path is not a regular file")
    target_bytes = target_path.read_bytes() if target_exists else None
    if target_bytes is not None and (
        len(target_bytes) != TARGET_ARCHIVE_SIZE
        or hashlib.sha256(target_bytes).hexdigest() != TARGET_ARCHIVE_SHA256
    ):
        raise PublicationConflictError("SCAG 1.0.3 target archive conflicts")
    if target_bytes is None:
        target_bytes = (archive_builder or _build_target_archive)(source_bytes)
        if (
            len(target_bytes) != TARGET_ARCHIVE_SIZE
            or hashlib.sha256(target_bytes).hexdigest() != TARGET_ARCHIVE_SHA256
        ):
            raise PublicationConflictError("rebuilt SCAG 1.0.3 archive conflicts")

    desired_files = [
        (target_path, target_bytes),
        (
            index_path,
            metadata_bytes[index_path]
            if index == desired_index
            else _object_bytes(
                desired_index, newline=_newline_for(metadata_bytes[index_path])
            ),
        ),
        (
            report_path,
            metadata_bytes[report_path]
            if report == desired_report
            else _object_bytes(
                desired_report, newline=_newline_for(metadata_bytes[report_path])
            ),
        ),
        (
            summary_path,
            metadata_bytes[summary_path]
            if summary == desired_summary
            else _object_bytes(
                desired_summary, newline=_newline_for(metadata_bytes[summary_path])
            ),
        ),
    ]
    writes = 0
    for path, content in desired_files:
        if path.exists() and path.read_bytes() == content:
            continue
        _atomic_replace(path, content)
        writes += 1
        if fail_after_replace == writes:
            raise InjectedPublicationFailure(
                f"injected failure after replacement {writes}"
            )
    return {
        "id": PACKAGE_ID,
        "version": TARGET_VERSION,
        "checksum": TARGET_CHECKSUM,
        "status": "already_current" if writes == 0 else "published",
        "writes": writes,
    }


def main() -> None:
    print(json.dumps(publish()))


if __name__ == "__main__":
    main()
