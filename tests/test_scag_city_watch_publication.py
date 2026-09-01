from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LIBRARY_ROOT = REPOSITORY_ROOT / "content-library"
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "republish_scag_city_watch_integrity.py"
SPEC = importlib.util.spec_from_file_location(
    "republish_scag_city_watch_integrity", SCRIPT_PATH
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


def _make_library(tmp_path: Path, *, current_metadata: bool = False) -> Path:
    root = tmp_path / "content-library"
    packages = root / "packages"
    packages.mkdir(parents=True)
    index = _read_json(LIBRARY_ROOT / "index.json")
    report = _read_json(LIBRARY_ROOT / "migration-report.json")
    summary = _read_json(LIBRARY_ROOT / "validation-summary.json")
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
            elif item.get("version") == publication.PREVIOUS_VERSION:
                retained.append(publication._previous_retained(target=False))
        report["superseded_archives"] = retained
        report["counts"]["superseded_archives"] = len(retained)
        summary["archive_validation"].update(
            {
                "bytes": 1062814222,
                "retained_superseded_archives": 1,
                "retained_superseded_bytes": publication.PREVIOUS_ARCHIVE_SIZE,
                "stored_archives": 47,
                "stored_bytes": 1063719289,
            }
        )
    _write_json(root / "index.json", index)
    _write_json(root / "migration-report.json", report)
    _write_json(root / "validation-summary.json", summary)
    (packages / Path(publication.SOURCE_PATH).name).write_bytes(
        (LIBRARY_ROOT / publication.SOURCE_PATH).read_bytes()
    )
    return root


def _target_bytes() -> bytes:
    return (LIBRARY_ROOT / publication.TARGET_PATH).read_bytes()


def _builder(source: bytes) -> bytes:
    assert len(source) == publication.SOURCE_ARCHIVE_SIZE
    return _target_bytes()


def _assert_current(root: Path) -> None:
    for name in ("index.json", "migration-report.json", "validation-summary.json"):
        assert _read_json(root / name) == _read_json(LIBRARY_ROOT / name)
    assert (root / publication.TARGET_PATH).read_bytes() == _target_bytes()
    assert not list(root.rglob("*.tmp"))


def test_fresh_publish_is_atomic_and_exact(tmp_path: Path) -> None:
    root = _make_library(tmp_path)
    result = publication.publish(root=root, archive_builder=_builder)
    assert result["status"] == "published"
    assert result["writes"] == 4
    _assert_current(root)


def test_exact_replay_is_a_validated_no_op(tmp_path: Path) -> None:
    root = _make_library(tmp_path, current_metadata=True)
    (root / publication.TARGET_PATH).write_bytes(_target_bytes())

    def unexpected_builder(_: bytes) -> bytes:
        raise AssertionError("exact replay must reuse the validated target archive")

    before = {
        path: path.read_bytes()
        for path in (
            root / publication.TARGET_PATH,
            root / "index.json",
            root / "migration-report.json",
            root / "validation-summary.json",
        )
    }
    result = publication.publish(root=root, archive_builder=unexpected_builder)
    assert result["status"] == "already_current"
    assert result["writes"] == 0
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("failure_point", [1, 2, 3, 4])
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


def test_exact_archive_with_old_metadata_recovers(tmp_path: Path) -> None:
    root = _make_library(tmp_path)
    (root / publication.TARGET_PATH).write_bytes(_target_bytes())
    result = publication.publish(root=root, archive_builder=_builder)
    assert result["writes"] == 3
    _assert_current(root)


def test_current_metadata_with_missing_archive_recovers(tmp_path: Path) -> None:
    root = _make_library(tmp_path, current_metadata=True)
    result = publication.publish(root=root, archive_builder=_builder)
    assert result["writes"] == 1
    _assert_current(root)


def test_arbitrary_old_and_new_metadata_mix_recovers(tmp_path: Path) -> None:
    root = _make_library(tmp_path)
    for name in ("migration-report.json", "validation-summary.json"):
        (root / name).write_bytes((LIBRARY_ROOT / name).read_bytes())
    (root / publication.TARGET_PATH).write_bytes(_target_bytes())
    result = publication.publish(root=root, archive_builder=_builder)
    assert result["writes"] == 1
    _assert_current(root)


def test_conflicting_target_archive_fails_closed(tmp_path: Path) -> None:
    root = _make_library(tmp_path)
    target = root / publication.TARGET_PATH
    target.write_bytes(b"conflicting finalized bytes")
    metadata_before = {
        name: (root / name).read_bytes()
        for name in ("index.json", "migration-report.json", "validation-summary.json")
    }
    with pytest.raises(publication.PublicationConflictError, match="target archive"):
        publication.publish(root=root, archive_builder=_builder)
    assert target.read_bytes() == b"conflicting finalized bytes"
    assert {
        name: (root / name).read_bytes() for name in metadata_before
    } == metadata_before


def test_conflicting_metadata_fails_before_archive_creation(tmp_path: Path) -> None:
    root = _make_library(tmp_path)
    index = _read_json(root / "index.json")
    scag = next(
        item for item in index["packages"] if item.get("id") == publication.PACKAGE_ID
    )
    scag["checksum"] = "0" * 64
    _write_json(root / "index.json", index)
    with pytest.raises(publication.PublicationConflictError, match="SCAG metadata"):
        publication.publish(root=root, archive_builder=_builder)
    assert not (root / publication.TARGET_PATH).exists()


def test_metadata_path_traversal_fails_before_writes(tmp_path: Path) -> None:
    root = _make_library(tmp_path)
    index = _read_json(root / "index.json")
    scag = next(
        item for item in index["packages"] if item.get("id") == publication.PACKAGE_ID
    )
    scag["path"] = "packages/../../outside.sagasmith-pack"
    _write_json(root / "index.json", index)
    with pytest.raises(
        publication.PublicationConflictError, match="unsafe archive path"
    ):
        publication.publish(root=root, archive_builder=_builder)
    assert not (root / publication.TARGET_PATH).exists()
