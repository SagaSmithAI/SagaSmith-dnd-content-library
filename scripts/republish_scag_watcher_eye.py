"""Publish the immutable SCAG correction that completes Watcher's Eye."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from sagasmith_core.content_pack import (
    build_content_package,
    dumps_content_archive,
    loads_content_archive,
)
from sagasmith_dnd.content_packages import validate_dnd_content_package
from sagasmith_dnd.content_validation import (
    build_catalog_review,
    build_selection_contract,
)

ROOT = Path(__file__).resolve().parents[1] / "content-library"
PACKAGE_ID = (
    "dnd5e.addon.rulebook.d-d-5e-sword-coast-adventurer-s-guide."
    "16e6a243ef0a.addon"
)
SOURCE_VERSION = "1.0.1"
SOURCE_CHECKSUM = "efbba0006ef837961a3d87203c60a49b1ed57428cdb10999aa8b6378964a5bb9"
SOURCE_ARCHIVE_SHA256 = (
    "d7e755e914f94871b0bf59966109e84f0ae2302776be9127bb558971d8d125d3"
)
TARGET_VERSION = "1.0.2"
PUBLISHED_ON = "2026-09-01"
CITY_WATCH_SUFFIX = ".background.city-watch"
INVESTIGATOR_SUFFIX = ".background.investigator"
FEATURE_TITLE = "FEATURE : WATCHER'S EYE"


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


def _one(values: list[dict[str, Any]], *, suffix: str) -> dict[str, Any]:
    matches = [value for value in values if str(value.get("id") or "").endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one artifact ending with {suffix!r}")
    return matches[0]


def _watchers_eye_source(
    package: dict[str, Any], blobs: dict[str, bytes]
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    sources = list(package.get("sources") or [])
    if len(sources) != 1:
        raise ValueError("SCAG Pack must expose exactly one indexed source")
    source = sources[0]
    sections = list(source.get("sections") or [])
    city_sections = [
        section
        for section in sections
        if str(section.get("title") or "").strip().upper() == "CITY WATCH"
    ]
    if len(city_sections) != 1:
        raise ValueError("SCAG source must expose exactly one City Watch section")
    city_section = city_sections[0]
    feature_sections = [
        section
        for section in sections
        if section.get("parent_ordinal") == city_section.get("ordinal")
        and str(section.get("title") or "").strip().upper() == FEATURE_TITLE
    ]
    if len(feature_sections) != 1:
        raise ValueError("City Watch must expose exactly one Watcher's Eye child section")
    feature = feature_sections[0]
    chunks = list(feature.get("chunks") or [])
    if len(chunks) != 1:
        raise ValueError("Watcher's Eye must map to exactly one source chunk")
    chunk = chunks[0]
    asset_key = str(source.get("normalized_document_asset_key") or "")
    assets = [asset for asset in package.get("assets") or [] if asset.get("asset_key") == asset_key]
    if len(assets) != 1:
        raise ValueError("SCAG normalized source asset is missing or ambiguous")
    checksum = str(assets[0].get("checksum") or "")
    normalized = blobs[checksum].decode("utf-8")
    text = normalized[int(feature["start_offset"]) : int(feature["end_offset"])]
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != feature.get("content_hash"):
        raise ValueError("Watcher's Eye source offsets do not match the indexed hash")
    return text.strip(), source, chunk


def _correct_package(
    package: dict[str, Any], blobs: dict[str, bytes]
) -> dict[str, Any]:
    if (
        package.get("id") != PACKAGE_ID
        or package.get("version") != SOURCE_VERSION
        or package.get("checksum") != SOURCE_CHECKSUM
    ):
        raise ValueError("SCAG source Pack identity is not the reviewed 1.0.1 archive")
    corrected = copy.deepcopy(package)
    text, source, chunk = _watchers_eye_source(corrected, blobs)
    artifacts = list(corrected["content"]["artifacts"])
    city_watch = _one(artifacts, suffix=CITY_WATCH_SUFFIX)
    investigator = _one(artifacts, suffix=INVESTIGATOR_SUFFIX)
    investigator_before = copy.deepcopy(investigator)

    feature_heading = "Feature: Watcher's Eye"
    city_watch["card"]["description"] += f" {feature_heading} {text}"
    ruling = city_watch["card"]["ruling_requirements"]
    if len(ruling) != 1:
        raise ValueError("City Watch must retain one source-bound ruling boundary")
    ruling[0]["source_excerpt"] += f" {feature_heading} {text}"

    source_key = str(source["source_key"])
    chunk_key = str(chunk["key"])
    source_citation = {
        "source": f"rule-source:{source_key}",
        "source_excerpt": text,
        "source_ref": {"chunk_key": chunk_key},
    }
    clauses = list(city_watch.get("rule_clauses") or [])
    if len(clauses) != 1:
        raise ValueError("City Watch must retain one narrative ruling clause")
    clauses[0]["source_citations"].append(source_citation)
    city_watch["rule_refs"].append(f"rule-source:{source_key}#chunk:{chunk_key}")
    city_watch["source_refs"].append(
        {
            "chunk_key": chunk_key,
            "note": "Watcher's Eye feature evidence",
            "page": int(chunk["page_start"]),
            "source_key": source_key,
        }
    )

    old_contract = dict(city_watch["selection_contract"])
    references = [*old_contract["references"], f"rule-source-chunk:{chunk_key}"]
    city_watch["selection_contract"] = build_selection_contract(
        city_watch,
        status=str(old_contract["status"]),
        materializer=str(old_contract["materializer"]),
        schema=old_contract["schema"],
        references=references,
        blockers=old_contract["blockers"],
    )
    decisions = copy.deepcopy(city_watch["catalog_review"]["decisions"])
    city_watch["catalog_review"] = build_catalog_review(
        city_watch,
        decisions=decisions,
        status="approved",
    )
    if investigator != investigator_before:
        raise AssertionError("Investigator must remain an independent unchanged variant")

    metadata = copy.deepcopy(corrected["metadata"])
    metadata["source_correction"] = {
        "schema": "sagasmith.pack-source-correction.v1",
        "source_version": SOURCE_VERSION,
        "source_checksum": SOURCE_CHECKSUM,
        "updated_on": PUBLISHED_ON,
        "changes": [
            "completed the City Watch Watcher's Eye narrative source excerpt",
            "added the exact indexed Watcher's Eye source references",
            "preserved Investigator as an independent background variant",
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


def main() -> None:
    index_path = ROOT / "index.json"
    report_path = ROOT / "migration-report.json"
    summary_path = ROOT / "validation-summary.json"
    index = _read_object(index_path)
    report = _read_object(report_path)
    summary = _read_object(summary_path)
    matches = [item for item in index["packages"] if item.get("id") == PACKAGE_ID]
    if len(matches) != 1:
        raise ValueError("current index must contain exactly one SCAG Pack")
    current = matches[0]
    if current.get("version") != SOURCE_VERSION or current.get("checksum") != SOURCE_CHECKSUM:
        raise ValueError("current SCAG Pack is not the reviewed 1.0.1 source")
    old_path = (ROOT / str(current["path"])).resolve()
    package_root = (ROOT / "packages").resolve()
    if old_path.parent != package_root or not old_path.is_file():
        raise ValueError("current SCAG archive is outside packages/")
    old_bytes = old_path.read_bytes()
    if hashlib.sha256(old_bytes).hexdigest() != SOURCE_ARCHIVE_SHA256:
        raise ValueError("current SCAG archive bytes differ from the finalized source")
    package, blobs = loads_content_archive(old_bytes)
    rebuilt = _correct_package(package, blobs)
    archive = dumps_content_archive(rebuilt, blobs)
    filename = f"{rebuilt['checksum'][:12]}-{PACKAGE_ID}-{TARGET_VERSION}.sagasmith-pack"
    new_path = package_root / filename
    if new_path.exists() and new_path.read_bytes() != archive:
        raise RuntimeError("target archive already exists with different bytes")
    new_path.write_bytes(archive)

    replacement = {
        **current,
        "action": "source_corrected_current",
        "source_version": SOURCE_VERSION,
        "source_checksum": SOURCE_CHECKSUM,
        "version": TARGET_VERSION,
        "checksum": str(rebuilt["checksum"]),
        "archive_sha256": hashlib.sha256(archive).hexdigest(),
        "archive_size": len(archive),
        "source_path": str(current["path"]),
        "path": f"packages/{filename}",
    }
    index["generated_on"] = PUBLISHED_ON
    index["packages"] = [replacement if item.get("id") == PACKAGE_ID else item for item in index["packages"]]
    report["generated_on"] = PUBLISHED_ON
    report["packages"] = copy.deepcopy(index["packages"])
    retained = {
        "identity": [str(current["system_id"]), str(current["kind"]), PACKAGE_ID],
        "version": SOURCE_VERSION,
        "checksum": SOURCE_CHECKSUM,
        "path": str(current["path"]),
        "archive_sha256": SOURCE_ARCHIVE_SHA256,
        "archive_size": len(old_bytes),
        "retained_finalized": True,
        "superseded_by": {
            "version": TARGET_VERSION,
            "checksum": str(rebuilt["checksum"]),
        },
    }
    report["superseded_archives"].append(retained)
    report["counts"]["superseded_archives"] = len(report["superseded_archives"])
    archive_validation = summary["archive_validation"]
    current_bytes = sum((ROOT / str(item["path"])).stat().st_size for item in index["packages"])
    archive_validation["bytes"] = current_bytes
    archive_validation["retained_superseded_archives"] = 1
    archive_validation["retained_superseded_bytes"] = len(old_bytes)
    archive_validation["stored_archives"] = len(index["packages"]) + 1
    archive_validation["stored_bytes"] = current_bytes + len(old_bytes)
    _write_object(index_path, index)
    _write_object(report_path, report)
    _write_object(summary_path, summary)
    print(json.dumps({"id": PACKAGE_ID, "version": TARGET_VERSION, "checksum": rebuilt["checksum"]}))


if __name__ == "__main__":
    main()
