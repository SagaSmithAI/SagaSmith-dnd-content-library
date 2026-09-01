"""Publish the immutable SCAG City Watch and Investigator integrity correction."""

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
    "dnd5e.addon.rulebook.d-d-5e-sword-coast-adventurer-s-guide.16e6a243ef0a.addon"
)
SOURCE_VERSION = "1.0.2"
SOURCE_CHECKSUM = "5e5504ec3d2ebb82e548a48c6b97f49938ed9d08bf94d6efaa08600a11ab3c22"
SOURCE_ARCHIVE_SHA256 = (
    "63546d562fb921391202e10232733d45e818c71ed1d6cbdd164c11b1fb82359d"
)
TARGET_VERSION = "1.0.3"
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
    if (
        current.get("version") != SOURCE_VERSION
        or current.get("checksum") != SOURCE_CHECKSUM
    ):
        raise ValueError("current SCAG Pack is not the reviewed 1.0.2 source")
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
    filename = (
        f"{rebuilt['checksum'][:12]}-{PACKAGE_ID}-{TARGET_VERSION}.sagasmith-pack"
    )
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
    index["packages"] = [
        replacement if item.get("id") == PACKAGE_ID else item
        for item in index["packages"]
    ]
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
    for item in report["superseded_archives"]:
        if (
            item.get("retained_finalized") is True
            and list(item.get("identity") or [None, None, None])[2] == PACKAGE_ID
        ):
            item["superseded_by"] = {
                "version": TARGET_VERSION,
                "checksum": str(rebuilt["checksum"]),
            }
    report["superseded_archives"].append(retained)
    report["counts"]["superseded_archives"] = len(report["superseded_archives"])
    archive_validation = summary["archive_validation"]
    current_bytes = sum(
        (ROOT / str(item["path"])).stat().st_size for item in index["packages"]
    )
    retained_archives = [
        item
        for item in report["superseded_archives"]
        if item.get("retained_finalized") is True
    ]
    retained_bytes = sum(int(item["archive_size"]) for item in retained_archives)
    archive_validation["bytes"] = current_bytes
    archive_validation["retained_superseded_archives"] = len(retained_archives)
    archive_validation["retained_superseded_bytes"] = retained_bytes
    archive_validation["stored_archives"] = len(index["packages"]) + len(
        retained_archives
    )
    archive_validation["stored_bytes"] = current_bytes + retained_bytes
    _write_object(index_path, index)
    _write_object(report_path, report)
    _write_object(summary_path, summary)
    print(
        json.dumps(
            {
                "id": PACKAGE_ID,
                "version": TARGET_VERSION,
                "checksum": rebuilt["checksum"],
            }
        )
    )


if __name__ == "__main__":
    main()
