from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "content-library"
PACKAGE_ID = (
    "dnd5e.addon.rulebook.d-d-5e-sword-coast-adventurer-s-guide.16e6a243ef0a.addon"
)
ARTIFACT_PREFIX = PACKAGE_ID.removesuffix(".addon")


def _current_package() -> tuple[dict, dict, zipfile.ZipFile]:
    index = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))
    item = next(entry for entry in index["packages"] if entry["id"] == PACKAGE_ID)
    archive = zipfile.ZipFile(ROOT / item["path"])
    package = json.loads(archive.read("package.sagasmith.json"))
    return item, package, archive


def _artifact(package: dict, suffix: str) -> dict:
    matches = [
        artifact
        for artifact in package["content"]["artifacts"]
        if artifact["id"].endswith(suffix)
    ]
    assert len(matches) == 1
    return matches[0]


def _section_texts(
    package: dict, archive: zipfile.ZipFile
) -> dict[str, tuple[dict, str]]:
    source = package["sources"][0]
    asset = next(
        item
        for item in package["assets"]
        if item["asset_key"] == source["normalized_document_asset_key"]
    )
    normalized = archive.read(asset["blob_key"]).decode("utf-8")
    expected = {
        "CITY WATCH",
        "FEATURE : WATCHER'S EYE",
        "VARIANT: INVESTIGATOR",
    }
    result = {}
    for section in source["sections"]:
        if section["title"] not in expected:
            continue
        text = normalized[section["start_offset"] : section["end_offset"]]
        assert (
            hashlib.sha256(text.encode("utf-8")).hexdigest() == section["content_hash"]
        )
        result[section["title"]] = (section, text)
    assert set(result) == expected
    return result


def test_city_watch_uses_complete_source_bound_equipment() -> None:
    item, package, archive = _current_package()
    try:
        assert (
            item["version"]
            == package["version"]
            == "1.0.5-local.subclass-grants.1"
        )
        assert item["checksum"] == package["checksum"]
        city_watch = _artifact(package, ".background.city-watch")
        grants = city_watch["card"]["background_grants"]
        items = grants["equipment"]["items"]
        assert items == [
            {
                "inventory_template": {
                    "description": "Source-reviewed background equipment.",
                    "kind": "equipment",
                    "mechanics": {},
                    "name": "Watch Uniform",
                    "quantity": 1,
                }
            },
            {"artifact_id": "dnd5e.content.srd2014.item.horn", "quantity": 1},
            {"artifact_id": "dnd5e.content.srd2014.item.manacles", "quantity": 1},
            {"artifact_id": "dnd5e.content.srd2014.item.pouch", "quantity": 1},
        ]
        assert grants["equipment"]["wallet"] == {"gp": 10}
        assert grants["choices"]["equipment_description"].endswith(
            "a set of manacles, and a pouch containing 10 gp"
        )
        assert (
            city_watch["selection_contract"]["schema"]["card_binding"][
                "background_grants"
            ]
            == grants
        )
        selection_hash = city_watch["selection_contract"]["reviewed_content_hash"]
        assert selection_hash == city_watch["catalog_review"]["reviewed_content_hash"]
        assert len(selection_hash) == 64
        int(selection_hash, 16)
    finally:
        archive.close()


def test_investigator_inherits_city_watch_except_for_the_exact_skill_replacement() -> (
    None
):
    _, package, archive = _current_package()
    try:
        city_watch = _artifact(package, ".background.city-watch")
        investigator = _artifact(package, ".background.investigator")
        source = package["sources"][0]
        sections = _section_texts(package, archive)
        city_grants = city_watch["card"]["background_grants"]
        investigator_grants = investigator["card"]["background_grants"]
        assert investigator_grants == {
            **city_grants,
            "skills": ["Investigation", "Insight"],
        }
        assert investigator["card"]["skill_proficiencies"] == [
            "Investigation",
            "Insight",
        ]
        assert investigator_grants["equipment"] == city_grants["equipment"]
        assert [
            dict(item.get("inventory_template") or {}).get("name")
            for item in investigator_grants["equipment"]["items"]
            if item.get("inventory_template")
        ] == ["Watch Uniform"]

        expected_chunks = [
            sections[title][0]["chunks"][0]["key"]
            for title in (
                "CITY WATCH",
                "FEATURE : WATCHER'S EYE",
                "VARIANT: INVESTIGATOR",
            )
        ]
        assert investigator["rule_refs"] == [
            f"rule-source:{source['source_key']}#chunk:{chunk}"
            for chunk in expected_chunks
        ]
        assert investigator["selection_contract"]["references"] == [
            f"rule-source-chunk:{chunk}" for chunk in expected_chunks
        ]
        assert [
            item["chunk_key"] for item in investigator["source_refs"]
        ] == expected_chunks
        assert [
            item["source_ref"]["chunk_key"]
            for item in investigator["rule_clauses"][0]["source_citations"]
        ] == expected_chunks
        for _, text in sections.values():
            assert investigator["card"]["description"].count(text.strip()) == 1
            assert (
                investigator["card"]["ruling_requirements"][0]["source_excerpt"].count(
                    text.strip()
                )
                == 1
            )
        assert (
            investigator["selection_contract"]["schema"]["card_binding"][
                "background_grants"
            ]
            == investigator_grants
        )
        selection_hash = investigator["selection_contract"]["reviewed_content_hash"]
        assert selection_hash == investigator["catalog_review"]["reviewed_content_hash"]
        assert len(selection_hash) == 64
        int(selection_hash, 16)
    finally:
        archive.close()
