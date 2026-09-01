from __future__ import annotations

import copy
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LIBRARY_ROOT = REPOSITORY_ROOT / "content-library"
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "republish_scag_definition_checksum.py"
SPEC = importlib.util.spec_from_file_location(
    "republish_scag_definition_checksum", SCRIPT_PATH
)
assert SPEC is not None and SPEC.loader is not None
publication = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publication)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _target_bytes() -> bytes:
    return (LIBRARY_ROOT / publication.TARGET_PATH).read_bytes()


def _builder(source: bytes) -> bytes:
    assert len(source) == publication.SOURCE_ARCHIVE_SIZE
    return _target_bytes()


def _make_library(tmp_path: Path, *, current_metadata: bool = False) -> Path:
    root = tmp_path / "content-library"
    packages = root / "packages"
    packages.mkdir(parents=True)
    index = _read_json(LIBRARY_ROOT / "index.json")
    report = _read_json(LIBRARY_ROOT / "migration-report.json")
    summary = _read_json(LIBRARY_ROOT / "validation-summary.json")
    evidence = _read_json(LIBRARY_ROOT / "import-evidence.json")
    if not current_metadata:
        index["packages"] = [
            publication._source_entry()
            if item.get("id") == publication.PACKAGE_ID
            else item
            for item in index["packages"]
        ]
        report["packages"] = copy.deepcopy(index["packages"])
        retained = []
        for item in report["superseded_archives"]:
            if not publication._is_scag_retained(item):
                retained.append(item)
            elif item.get("version") != publication.SOURCE_VERSION:
                prior = next(
                    value
                    for value in publication.PRIOR_ARCHIVES
                    if value["version"] == item["version"]
                )
                retained.append(publication._retained_entry(prior, target=False))
        report["superseded_archives"] = retained
        report["counts"]["superseded_archives"] = len(retained)
        summary["archive_validation"].update(
            {
                "bytes": 1062814386,
                "retained_superseded_archives": 2,
                "retained_superseded_bytes": 1810551,
                "stored_archives": 48,
                "stored_bytes": 1064624937,
            }
        )
        evidence["dnd"] = [
            publication._source_evidence()
            if item.get("id") == publication.PACKAGE_ID
            else item
            for item in evidence["dnd"]
        ]
    for name, value in (
        ("index.json", index),
        ("migration-report.json", report),
        ("validation-summary.json", summary),
        ("import-evidence.json", evidence),
    ):
        _write_json(root / name, value)
    (root / publication.SOURCE_PATH).write_bytes(
        (LIBRARY_ROOT / publication.SOURCE_PATH).read_bytes()
    )
    return root


def _assert_current(root: Path) -> None:
    for name in (
        "index.json",
        "migration-report.json",
        "validation-summary.json",
        "import-evidence.json",
    ):
        assert _read_json(root / name) == _read_json(LIBRARY_ROOT / name)
    assert (root / publication.TARGET_PATH).read_bytes() == _target_bytes()
    assert not list(root.rglob("*.tmp"))


def _symlink_or_skip(link: Path, target: Path, *, directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable: {error}")


def test_current_definition_checksum_matches_every_exact_input() -> None:
    with zipfile.ZipFile(LIBRARY_ROOT / publication.TARGET_PATH) as archive:
        package = json.loads(archive.read("package.sagasmith.json"))
    definitions = package["content"]["rule_definitions"]
    assert len(definitions) == 1
    for definition in definitions:
        definition_id = definition["id"]
        artifacts = [
            item
            for item in package["content"]["artifacts"]
            if item.get("rule_definition_id") == definition_id
        ]
        mechanics = [
            item
            for item in package["content"]["mechanics"]
            if item.get("rule_definition_id") == definition_id
        ]
        recomputed = publication.definition_checksum(
            manifest=definition["manifest"],
            artifacts=artifacts,
            mechanics=mechanics,
        )
        assert (len(artifacts), len(mechanics)) == (108, 0)
        assert definition["definition_checksum"] == recomputed
        assert recomputed == publication.TARGET_DEFINITION_CHECKSUM
    correction = package["metadata"]["definition_checksum_correction"]
    assert correction["algorithm"] == "sagasmith-dnd.content-definition-checksum.v1"
    assert correction["definitions"][0]["definition_checksum"] == recomputed


def test_immutable_release_changes_only_checksum_identity_and_metadata() -> None:
    with zipfile.ZipFile(LIBRARY_ROOT / publication.SOURCE_PATH) as source_archive:
        source = json.loads(source_archive.read("package.sagasmith.json"))
    with zipfile.ZipFile(LIBRARY_ROOT / publication.TARGET_PATH) as target_archive:
        target = json.loads(target_archive.read("package.sagasmith.json"))
    assert target["content"]["artifacts"] == source["content"]["artifacts"]
    assert target["content"]["mechanics"] == source["content"]["mechanics"]
    assert (
        target["content"]["rule_definitions"][0]["manifest"]
        == source["content"]["rule_definitions"][0]["manifest"]
    )
    normalized = copy.deepcopy(target)
    normalized["version"] = source["version"]
    normalized["checksum"] = source["checksum"]
    normalized["manifest"]["version"] = source["manifest"]["version"]
    normalized["metadata"].pop("definition_checksum_correction")
    normalized["content"]["rule_definitions"][0]["definition_checksum"] = (
        publication.SOURCE_DEFINITION_CHECKSUM
    )
    assert normalized == source


def test_recompute_changes_definition_identity_after_artifact_change() -> None:
    package = {
        "content": {
            "rule_definitions": [
                {
                    "id": "dnd5e.test.definition",
                    "definition_checksum": "0" * 64,
                    "manifest": {"title": "Test"},
                }
            ],
            "artifacts": [
                {
                    "id": "dnd5e.test.artifact",
                    "rule_definition_id": "dnd5e.test.definition",
                    "card": {"value": 1},
                }
            ],
            "mechanics": [],
        }
    }
    first = publication.recompute_definition_checksums(package)[0][
        "definition_checksum"
    ]
    package["content"]["artifacts"][0]["card"]["value"] = 2
    second = publication.recompute_definition_checksums(package)[0][
        "definition_checksum"
    ]
    assert first != second
    assert package["content"]["rule_definitions"][0]["definition_checksum"] == second


def test_fresh_publish_converges_to_committed_state(tmp_path: Path) -> None:
    root = _make_library(tmp_path)
    result = publication.publish(root=root, archive_builder=_builder)
    assert result["status"] == "published"
    assert result["writes"] == 5
    _assert_current(root)


def test_exact_replay_is_a_validated_no_op(tmp_path: Path) -> None:
    root = _make_library(tmp_path, current_metadata=True)
    (root / publication.TARGET_PATH).write_bytes(_target_bytes())

    def unexpected_builder(_: bytes) -> bytes:
        raise AssertionError("exact replay must reuse the target archive")

    result = publication.publish(root=root, archive_builder=unexpected_builder)
    assert result["status"] == "already_current"
    assert result["writes"] == 0


@pytest.mark.parametrize("failure_point", [1, 2, 3, 4, 5])
def test_every_interrupted_replacement_recovers(
    tmp_path: Path, failure_point: int
) -> None:
    root = _make_library(tmp_path)
    with pytest.raises(publication.InjectedPublicationFailure):
        publication.publish(
            root=root,
            archive_builder=_builder,
            fail_after_replace=failure_point,
        )
    assert not list(root.rglob("*.tmp"))
    publication.publish(root=root, archive_builder=_builder)
    _assert_current(root)


def test_arbitrary_old_and_new_metadata_mix_recovers(tmp_path: Path) -> None:
    root = _make_library(tmp_path)
    for name in ("migration-report.json", "import-evidence.json"):
        (root / name).write_bytes((LIBRARY_ROOT / name).read_bytes())
    (root / publication.TARGET_PATH).write_bytes(_target_bytes())
    publication.publish(root=root, archive_builder=_builder)
    _assert_current(root)


def test_conflicting_target_archive_fails_closed(tmp_path: Path) -> None:
    root = _make_library(tmp_path)
    target = root / publication.TARGET_PATH
    target.write_bytes(b"conflict")
    with pytest.raises(publication.PublicationConflictError, match="target archive"):
        publication.publish(root=root, archive_builder=_builder)
    assert target.read_bytes() == b"conflict"


@pytest.mark.parametrize("metadata_name", ["index.json", "import-evidence.json"])
def test_conflicting_metadata_fails_before_archive_creation(
    tmp_path: Path, metadata_name: str
) -> None:
    root = _make_library(tmp_path)
    value = _read_json(root / metadata_name)
    collection = value["packages"] if metadata_name == "index.json" else value["dnd"]
    item = next(
        entry for entry in collection if entry.get("id") == publication.PACKAGE_ID
    )
    item["checksum"] = "0" * 64
    _write_json(root / metadata_name, value)
    with pytest.raises(publication.PublicationConflictError, match="SCAG"):
        publication.publish(root=root, archive_builder=_builder)
    assert not (root / publication.TARGET_PATH).exists()


def test_metadata_path_traversal_fails_before_writes(tmp_path: Path) -> None:
    root = _make_library(tmp_path)
    index = _read_json(root / "index.json")
    item = next(
        entry
        for entry in index["packages"]
        if entry.get("id") == publication.PACKAGE_ID
    )
    item["path"] = "packages/../../outside.sagasmith-pack"
    _write_json(root / "index.json", index)
    with pytest.raises(
        publication.PublicationConflictError, match="unsafe archive path"
    ):
        publication.publish(root=root, archive_builder=_builder)
    assert not (root / publication.TARGET_PATH).exists()


def test_packages_directory_link_is_rejected_without_external_write(
    tmp_path: Path,
) -> None:
    root = _make_library(tmp_path)
    packages = root / "packages"
    (root / publication.SOURCE_PATH).unlink()
    packages.rmdir()
    outside = tmp_path / "outside-packages"
    outside.mkdir()
    marker = outside / "marker"
    marker.write_bytes(b"unchanged")
    _symlink_or_skip(packages, outside, directory=True)
    with pytest.raises(publication.PublicationConflictError, match="link or reparse"):
        publication.publish(root=root, archive_builder=_builder)
    assert marker.read_bytes() == b"unchanged"
    assert not (outside / Path(publication.TARGET_PATH).name).exists()


@pytest.mark.parametrize("archive_kind", ["source", "target"])
def test_archive_file_link_outside_root_is_rejected(
    tmp_path: Path, archive_kind: str
) -> None:
    root = _make_library(tmp_path)
    if archive_kind == "source":
        archive = root / publication.SOURCE_PATH
        outside = tmp_path / "outside-source.sagasmith-pack"
        outside.write_bytes(archive.read_bytes())
        archive.unlink()
    else:
        archive = root / publication.TARGET_PATH
        outside = tmp_path / "outside-target.sagasmith-pack"
        outside.write_bytes(_target_bytes())
    before = outside.read_bytes()
    _symlink_or_skip(archive, outside, directory=False)
    with pytest.raises(
        publication.PublicationConflictError, match="must not be a link"
    ):
        publication.publish(root=root, archive_builder=_builder)
    assert outside.read_bytes() == before
