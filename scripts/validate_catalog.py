"""Validate a private or public unified catalog without importing SagaSmith."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DESCRIPTOR = "package.sagasmith.json"
PRIVATE_COUNTS = {"addon": 18, "core_rules": 3, "module": 7, "preset": 2}
PUBLIC_COUNTS = {"preset": 2}
EXPECTED_CORE_IDS = {
    "dnd5e.core-rules.dmg2014",
    "dnd5e.core-rules.mm2014",
    "dnd5e.core-rules.phb2014",
}
BROWSER_ASSET_KINDS = {"actor_image", "map", "normalized_document", "player_reference"}
EXPECTED_MODULE_AUXILIARY = {
    "dnd5e.module.lost-mine-of-phandelver": {
        "Lost Mine of Phandelver/PC-Smalls.pdf",
        "Lost Mine of Phandelver/Sword Coast Map.png",
    },
    "dnd5e.module.storm-kings-thunder": {
        "Storm King's Thunder/DrippingCaves.png",
        "Storm King's Thunder/Nightstone.png",
        "Storm King's Thunder/SKT-PCStats.txt",
        "Storm King's Thunder/Characters/AncestralGuardianBarbarian.pdf",
        "Storm King's Thunder/Characters/HunterRanger.pdf",
        "Storm King's Thunder/Characters/OpenHandMonk.pdf",
        "Storm King's Thunder/Characters/ShadowSorcerer.pdf",
        "Storm King's Thunder/Characters/TempestCleric.pdf",
        "Storm King's Thunder/Characters/VengencePaladin.pdf",
        "Storm King's Thunder/Characters/WildSorcerer.pdf",
    },
}


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO / "public" / "content-library",
    )
    args = parser.parse_args()
    root = args.root
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    audit = json.loads((root / "audit.json").read_text(encoding="utf-8"))
    visibility = index["visibility"]
    assert visibility in {"private", "public"}
    assert index["schema"] == "sagasmith.content-library.v1"
    assert audit["schema"] == "sagasmith.content-library-audit.v1"
    assert audit["visibility"] == visibility
    assert index["package_format"] == "sagasmith.content-package"
    assert index["blob_base_path"] == "blobs/sha256"
    assert set(index["browser_asset_kinds"]) == BROWSER_ASSET_KINDS
    expected_package_files: set[Path] = set()
    expected_public_blobs: set[Path] = set()
    identities: set[tuple[str, str, str]] = set()
    counts: Counter[str] = Counter()
    image_count = 0
    packages = []
    statblock_card_counts: dict[str, int] = {}
    statblock_image_counts: dict[str, int] = {}
    for entry in index["packages"]:
        descriptor_path = root / entry["path"]
        archive_path = root / entry["download_path"]
        expected_package_files.update({descriptor_path.resolve(), archive_path.resolve()})
        archive_bytes = archive_path.read_bytes()
        assert len(archive_bytes) == entry["archive_size"]
        assert hashlib.sha256(archive_bytes).hexdigest() == entry["archive_checksum"]
        package = json.loads(descriptor_path.read_text(encoding="utf-8"))
        assert package["format"] == "sagasmith.content-package", descriptor_path
        assert package["schema_version"] == 2, descriptor_path
        assert "readiness" not in package, descriptor_path
        assert package["kind"] in {"addon", "core_rules", "module", "preset"}
        assert package["manifest"]["id"] == package["id"]
        assert package["manifest"]["version"] == package["version"]
        assert package["manifest"]["system_id"] == package["system_id"]
        assert package["metadata"]["distribution"] == visibility
        assert package["metadata"]["license"]
        assert package["metadata"]["attribution"]
        if visibility == "public":
            assert package["metadata"]["license"] == "CC-BY-4.0"
            assert set(package["metadata"]["license_evidence"]) == {
                "type",
                "license_url",
                "source_url",
            }
            assert package["metadata"]["license_evidence"]["type"] == "open_license"
        unsigned = {key: value for key, value in package.items() if key != "checksum"}
        checksum = hashlib.sha256(canonical_json(unsigned).encode()).hexdigest()
        assert checksum == package["checksum"] == entry["checksum"], descriptor_path
        identity = (package["kind"], package["id"], package["version"])
        assert identity not in identities, identity
        assert identity == (entry["kind"], entry["id"], entry["version"])
        identities.add(identity)
        packages.append(package)
        counts[package["kind"]] += 1
        image_count += entry["image_count"]
        expected_assets = {asset["checksum"]: asset for asset in package["assets"]}
        assets_by_key = {asset["asset_key"]: asset for asset in package["assets"]}
        assert len(assets_by_key) == len(package["assets"])
        if package["kind"] == "module":
            finalization = package["metadata"]["agent_finalization"]
            assert set(finalization) == {"confirmed", "reviewer", "note"}
            assert finalization["confirmed"] is True
            assert str(finalization["reviewer"]).strip()
            assert str(finalization["note"]).strip()
            profile = package["content"]["play_profile"]
            assert profile["party_size"]["minimum"] is not None
            assert profile["party_size"]["maximum"] is not None
            assert profile["starting_level"]["value"] is not None
            assert profile["expected_end_level"]["value"] is not None
            assert profile["advancement"]["recommended"] != "unknown"
            for field in (
                "party_size",
                "starting_level",
                "expected_end_level",
                "advancement",
                "pregenerated_characters",
            ):
                assert profile[field]["source_refs"]
        sources_by_key = {source["source_key"]: source for source in package["sources"]}
        assert len(sources_by_key) == len(package["sources"])
        chunks_by_source = {
            source["source_key"]: {
                chunk["key"]
                for section in source["sections"]
                for chunk in section["chunks"]
            }
            for source in package["sources"]
        }
        for source in package["sources"]:
            normalized = assets_by_key[source["normalized_document_asset_key"]]
            assert normalized["kind"] == "normalized_document"
            if source["authority"] != "preset":
                assert source["original_asset_keys"], source["source_key"]
            for asset_key in source["original_asset_keys"]:
                assert assets_by_key[asset_key]["kind"] == "original_document"
        assert not any(asset["kind"] == "source_asset" for asset in package["assets"])
        actual_auxiliary = {
            asset["metadata"]["logical_path"]
            for asset in package["assets"]
            if asset["metadata"].get("relationship") == "package_auxiliary"
        }
        assert actual_auxiliary == EXPECTED_MODULE_AUXILIARY.get(package["id"], set())
        attached_images = 0
        actor_ids: set[str] = set()
        for actor in package["actors"]:
            assert actor["schema"] == "sagasmith.actor-card.v3"
            assert actor["system_id"] == package["system_id"]
            assert actor["id"] not in actor_ids
            actor_ids.add(actor["id"])
            image = actor["image"]
            if image is not None:
                attached_images += 1
                image_asset = assets_by_key[image["asset_key"]]
                assert image_asset["kind"] == "actor_image"
                assert image_asset["media_type"] == "image/webp"
                extraction = image_asset["metadata"]["extraction"]
                assert 0.40 <= extraction["confidence"] <= 1.0
                assert extraction["page"] >= 1
                assert len(extraction["crop"]) == 4
                left, top, right, bottom = extraction["crop"]
                assert left >= 0 and top >= 0 and right > left and bottom > top
                assert any(
                    ref["page"] == extraction["page"]
                    for ref in image_asset["source_refs"]
                )
            for source_ref in actor["provenance"]["source_refs"]:
                assert source_ref["source_key"] in sources_by_key
                assert source_ref["chunk_key"] in chunks_by_source[source_ref["source_key"]]
        assert attached_images == entry["image_count"]
        statblock_cards = [
            artifact
            for artifact in package["content"].get("artifacts") or []
            if artifact.get("kind") == "statblock"
            and isinstance(artifact.get("card"), dict)
        ]
        attached_statblock_images = 0
        for artifact in statblock_cards:
            image = artifact["card"].get("image")
            if image is None:
                continue
            attached_statblock_images += 1
            image_asset = assets_by_key[image["asset_key"]]
            assert image_asset["kind"] == "actor_image"
            assert image_asset["media_type"] == "image/webp"
        statblock_card_counts[package["id"]] = len(statblock_cards)
        statblock_image_counts[package["id"]] = attached_statblock_images
        for asset in package["assets"]:
            for source_ref in asset["source_refs"]:
                assert source_ref["source_key"] in sources_by_key
                assert source_ref["chunk_key"] in chunks_by_source[source_ref["source_key"]]
        with zipfile.ZipFile(archive_path) as archive:
            assert len(archive.namelist()) == len(set(archive.namelist()))
            assert all(
                not name.startswith(("/", "\\")) and ".." not in Path(name).parts
                for name in archive.namelist()
            )
            archived = json.loads(archive.read(DESCRIPTOR).decode("utf-8"))
            assert archived == package
            actual = {
                name[len("blobs/sha256/") :]
                for name in archive.namelist()
                if name != DESCRIPTOR
            }
            assert actual == set(expected_assets)
            for checksum, asset in expected_assets.items():
                data = archive.read(f"blobs/sha256/{checksum}")
                assert len(data) == asset["size"]
                assert hashlib.sha256(data).hexdigest() == checksum
                if asset["kind"] in BROWSER_ASSET_KINDS:
                    public_path = root / index["blob_base_path"] / checksum
                    expected_public_blobs.add(public_path.resolve())
                    assert public_path.read_bytes() == data
    actual_package_files = {
        path.resolve() for path in (root / "packages").iterdir() if path.is_file()
    }
    actual_public_blobs = {
        path.resolve()
        for path in (root / index["blob_base_path"]).iterdir()
        if path.is_file()
    }
    assert actual_package_files == expected_package_files
    assert actual_public_blobs == expected_public_blobs
    checksums = {
        (package["kind"], package["id"], package["version"]): package["checksum"]
        for package in packages
    }
    for package in packages:
        for dependency in package["dependencies"]:
            identity = (
                dependency["kind"],
                dependency["id"],
                dependency["version"],
            )
            if identity not in checksums:
                assert dependency["optional"], (package["id"], dependency)
            else:
                assert checksums[identity] == dependency["checksum"]
    expected_counts = PRIVATE_COUNTS if visibility == "private" else PUBLIC_COUNTS
    assert dict(counts) == audit["counts"] == expected_counts
    if visibility == "private":
        assert {
            package["id"] for package in packages if package["kind"] == "core_rules"
        } == EXPECTED_CORE_IDS
    else:
        assert {package["id"] for package in packages} == {
            "dnd5e.presets.srd2014",
            "dnd5e.presets.srd2024",
        }
        assert all(
            not package["actors"]
            or all(actor["image"] is None for actor in package["actors"])
            for package in packages
        )
    assert len(identities) == audit["total"]
    assert image_count == audit["images"]
    if visibility == "public":
        assert image_count == 0
        assert audit["excluded_private_packages"] == 28
        print(json.dumps({"packages": len(identities), "counts": counts}, default=dict))
        return
    assert audit["packages"] == [
        {
            "kind": entry["kind"],
            "id": entry["id"],
            "version": entry["version"],
            "checksum": entry["checksum"],
            "actors": entry["component_counts"]["actor_card"],
            "images": entry["image_count"],
            "validated": True,
        }
        for entry in index["packages"]
    ]
    assert set(audit["image_extraction"]) == {identity[1] for identity in identities}
    assert audit["content_card_images"] == sum(statblock_image_counts.values())
    for entry in index["packages"]:
        image_audit = audit["image_extraction"][entry["id"]]
        assert image_audit["images"] == entry["image_count"]
        statblock_cards = statblock_card_counts[entry["id"]]
        attached_statblock_images = statblock_image_counts[entry["id"]]
        assert image_audit["statblock_cards"] == statblock_cards
        assert image_audit["statblock_card_images"] == attached_statblock_images
        assert image_audit["subjects"] == image_audit["actors"] + statblock_cards
        assert image_audit["subject_images"] == (
            image_audit["images"] + attached_statblock_images
        )
        assert image_audit["subject_images"] == (
            image_audit["extracted"] + image_audit["reused"]
        )
        assert len(image_audit["missing"]) == (
            image_audit["subjects"] - image_audit["subject_images"]
        )
        assert image_audit["review_required"] == [], entry["id"]
        assert image_audit["complete"] is True, entry["id"]
        absent_subject_ids = {
            (item["subject_type"], item["subject_id"])
            for item in image_audit["illustration_absent"]
        }
        missing_subject_ids = {
            (item["subject_type"], item["subject_id"])
            for item in image_audit["missing"]
        }
        assert absent_subject_ids == missing_subject_ids, entry["id"]
        if entry["id"] == "dnd5e.presets.srd2014":
            assert image_audit["evidence_matched"] == image_audit["actors"]
        if entry["id"] == "dnd5e.presets.srd2024":
            assert image_audit["evidence_matched"] >= 288
    print(json.dumps({"packages": len(identities), "counts": counts}, default=dict))


if __name__ == "__main__":
    main()
