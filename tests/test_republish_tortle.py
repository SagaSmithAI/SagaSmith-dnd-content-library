from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

from sagasmith_core.content_pack import loads_content_archive

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LIBRARY_ROOT = REPOSITORY_ROOT / "content-library"
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "republish_tortle.py"
SPEC = importlib.util.spec_from_file_location("republish_tortle", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
publication = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publication)


def _target_path() -> Path:
    return LIBRARY_ROOT / publication.TARGET_PATH.format(
        checksum=publication.TARGET_CHECKSUM[:12]
    )


def _package(path: Path) -> dict:
    package, _blobs = loads_content_archive(path.read_bytes())
    return package


def test_source_chunk_overlap_is_removed_without_losing_refs() -> None:
    source_path = LIBRARY_ROOT / publication.SOURCE_PATH
    package, blobs = loads_content_archive(source_path.read_bytes())
    _source, chunks, merged = publication._source_chunks(package, blobs)
    assert [chunk["key"] for chunk, _text in chunks] == [
        "user.rulebook.d-d-5e-the-tortle-package.e3234de670/section-9/chunk-10-fb5a021f5935d9e8",
        "user.rulebook.d-d-5e-the-tortle-package.e3234de670/section-9/chunk-11-29741c0b8fe1d411",
    ]
    assert merged.count("Shell Defense.") == 1
    assert "\n\nnormal. Shell Defense." not in merged
    assert len(merged) == 2154


def test_target_contract_preserves_tortle_mechanics_and_source_refs() -> None:
    package = _package(_target_path())
    artifact = next(item for item in package["content"]["artifacts"] if item["id"] == publication.TORTLE_ID)
    assert package["version"] == publication.TARGET_VERSION
    assert package["checksum"] == publication.TARGET_CHECKSUM
    assert package["manifest"]["native_mechanic_refs"] == publication.MECHANIC_REFS
    assert artifact["mechanic_refs"] == publication.MECHANIC_REFS
    assert artifact["card"]["description"].count("Shell Defense.") == 1
    assert artifact["card"]["grants"]["natural_armor_base"] == 17
    assert artifact["card"]["grants"]["natural_armor_includes_dexterity"] is False
    features = {item["name"]: item for item in artifact["card"]["grants"]["features"]}
    assert features["Natural Armor"]["mechanic_refs"] == [publication.AC_MECHANIC_ID]
    shell = features["Shell Defense"]
    assert shell["mechanic_refs"] == [publication.SHELL_MECHANIC_ID]
    contract = shell["choices"]["standard_resolution"]
    assert contract["activation"] == "action"
    assert contract["emerge"] == "bonus_action"
    assert contract["effects"]["ac_bonus"] == 4
    assert contract["effects"]["saving_throw_advantage"] == ["strength", "constitution"]
    assert contract["effects"]["speed"] == 0
    assert contract["effects"]["dexterity_save_disadvantage"] is True
    assert len(contract["source_refs"]) == 2
    assert artifact["rule_refs"] == [
        "rule-source:" + ref["source_key"] + "#chunk:" + ref["chunk_key"]
        for ref in artifact["source_refs"]
    ]


def test_target_archive_is_deterministic_and_source_archive_is_unchanged() -> None:
    source_path = LIBRARY_ROOT / publication.SOURCE_PATH
    source_bytes = source_path.read_bytes()
    assert len(source_bytes) == publication.SOURCE_ARCHIVE_SIZE
    assert hashlib.sha256(source_bytes).hexdigest() == publication.SOURCE_ARCHIVE_SHA256
    target_bytes = _target_path().read_bytes()
    assert target_bytes == publication._build_target_archive(source_bytes)
    assert len(target_bytes) == publication.TARGET_ARCHIVE_SIZE
    assert hashlib.sha256(target_bytes).hexdigest() == publication.TARGET_ARCHIVE_SHA256


def test_exact_replay_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "content-library"
    shutil.copytree(LIBRARY_ROOT, root)
    before = {
        path.relative_to(root): path.read_bytes()
        for path in root.iterdir()
        if path.is_file()
    }

    def unexpected_builder(_: bytes) -> bytes:
        raise AssertionError("exact replay must reuse the validated target archive")

    result = publication.publish(root=root, archive_builder=unexpected_builder)
    assert result["status"] == "already_current"
    assert result["writes"] == 0
    after = {
        path.relative_to(root): path.read_bytes()
        for path in root.iterdir()
        if path.is_file()
    }
    assert after == before
