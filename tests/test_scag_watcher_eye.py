from __future__ import annotations

import copy
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "content-library"
PACKAGE_ID = (
    "dnd5e.addon.rulebook.d-d-5e-sword-coast-adventurer-s-guide."
    "16e6a243ef0a.addon"
)


def _descriptor(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read("package.sagasmith.json"))


def _artifact(package: dict, suffix: str) -> dict:
    matches = [
        artifact
        for artifact in package["content"]["artifacts"]
        if artifact["id"].endswith(suffix)
    ]
    assert len(matches) == 1
    return matches[0]


def test_scag_republication_preserves_finalized_source_and_investigator() -> None:
    index = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))
    report = json.loads((ROOT / "migration-report.json").read_text(encoding="utf-8"))
    current = next(item for item in index["packages"] if item["id"] == PACKAGE_ID)
    retained = [
        item
        for item in report["superseded_archives"]
        if item.get("retained_finalized") is True and item["identity"][2] == PACKAGE_ID
    ]
    assert len(retained) == 1
    retained_item = retained[0]
    assert current["version"] == "1.0.2"
    assert retained_item["version"] == "1.0.1"
    assert retained_item["superseded_by"] == {
        "version": current["version"],
        "checksum": current["checksum"],
    }
    old_path = ROOT / retained_item["path"]
    assert hashlib.sha256(old_path.read_bytes()).hexdigest() == retained_item["archive_sha256"]

    old_package = _descriptor(old_path)
    new_package = _descriptor(ROOT / current["path"])
    assert _artifact(new_package, ".background.investigator") == _artifact(
        old_package, ".background.investigator"
    )


def test_city_watch_has_one_complete_source_bound_watchers_eye() -> None:
    index = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))
    current = next(item for item in index["packages"] if item["id"] == PACKAGE_ID)
    path = ROOT / current["path"]
    with zipfile.ZipFile(path) as archive:
        package = json.loads(archive.read("package.sagasmith.json"))
        source = package["sources"][0]
        city_sections = [s for s in source["sections"] if s["title"] == "CITY WATCH"]
        assert len(city_sections) == 1
        feature_sections = [
            s
            for s in source["sections"]
            if s["parent_ordinal"] == city_sections[0]["ordinal"]
            and s["title"] == "FEATURE : WATCHER'S EYE"
        ]
        assert len(feature_sections) == 1
        section = feature_sections[0]
        asset = next(
            a
            for a in package["assets"]
            if a["asset_key"] == source["normalized_document_asset_key"]
        )
        normalized = archive.read(asset["blob_key"]).decode("utf-8")
        text = normalized[section["start_offset"] : section["end_offset"]]
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == section["content_hash"]

    city_watch = _artifact(package, ".background.city-watch")
    investigator = _artifact(package, ".background.investigator")
    chunk_key = section["chunks"][0]["key"]
    assert city_watch["card"]["description"].count(text) == 1
    assert city_watch["card"]["ruling_requirements"][0]["source_excerpt"].count(text) == 1
    assert [
        citation
        for clause in city_watch["rule_clauses"]
        for citation in clause["source_citations"]
        if citation["source_ref"]["chunk_key"] == chunk_key
    ] == [
        {
            "source": f"rule-source:{source['source_key']}",
            "source_excerpt": text,
            "source_ref": {"chunk_key": chunk_key},
        }
    ]
    assert city_watch["selection_contract"]["references"].count(
        f"rule-source-chunk:{chunk_key}"
    ) == 1
    assert city_watch["card"]["background_grants"]["feature"] == "Watcher's Eye"
    assert investigator["card"]["background_grants"]["feature"] == "Watcher's Eye"
    assert investigator["card"]["description"].count(text) == 0


def test_city_watch_selection_projection_did_not_change() -> None:
    report = json.loads((ROOT / "migration-report.json").read_text(encoding="utf-8"))
    current = next(item for item in report["packages"] if item["id"] == PACKAGE_ID)
    retained = next(
        item
        for item in report["superseded_archives"]
        if item.get("retained_finalized") is True and item["identity"][2] == PACKAGE_ID
    )
    old = _artifact(_descriptor(ROOT / retained["path"]), ".background.city-watch")
    new = _artifact(_descriptor(ROOT / current["path"]), ".background.city-watch")
    old_projection = copy.deepcopy(old["card"]["background_grants"])
    new_projection = copy.deepcopy(new["card"]["background_grants"])
    assert new_projection == old_projection
    assert new["application_state"] == "selection_ready"
    assert new["execution_state"] == "ruling_ready"
