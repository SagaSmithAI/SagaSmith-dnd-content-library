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


def _target_metrics() -> dict[str, int]:
    return {
        "bytes": 1062814386,
        "retained_superseded_archives": 2,
        "retained_superseded_bytes": publication.PREVIOUS_ARCHIVE_SIZE
        + publication.SOURCE_ARCHIVE_SIZE,
        "stored_archives": 48,
        "stored_bytes": 1064624937,
    }


def _make_library(tmp_path: Path, *, current_metadata: bool = False) -> Path:
    root = tmp_path / "content-library"
    packages = root / "packages"
    packages.mkdir(parents=True)
    index = _read_json(LIBRARY_ROOT / "index.json")
    report = _read_json(LIBRARY_ROOT / "migration-report.json")
    summary = _read_json(LIBRARY_ROOT / "validation-summary.json")
    if current_metadata:
        index["generated_on"] = publication.PUBLISHED_ON
        index["packages"] = [
            publication._target_entry()
            if item.get("id") == publication.PACKAGE_ID
            else item
            for item in index["packages"]
        ]
        report["generated_on"] = publication.PUBLISHED_ON
        report["packages"] = copy.deepcopy(index["packages"])
        report["superseded_archives"] = [
            item
            for item in report["superseded_archives"]
            if not publication._is_scag_retained(item)
        ] + [
            publication._previous_retained(target=True),
            publication._source_retained(),
        ]
        report["counts"]["superseded_archives"] = len(
            report["superseded_archives"]
        )
        summary["archive_validation"].update(_target_metrics())
    else:
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
    if current_metadata:
        (packages / Path(publication.TARGET_PATH).name).write_bytes(_target_bytes())
    return root


def _target_bytes() -> bytes:
    return (LIBRARY_ROOT / publication.TARGET_PATH).read_bytes()


def _symlink_or_skip(link: Path, target: Path, *, directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable: {error}")


def _builder(source: bytes) -> bytes:
    assert len(source) == publication.SOURCE_ARCHIVE_SIZE
    return _target_bytes()


def _assert_current(root: Path) -> None:
    index = _read_json(root / "index.json")
    report = _read_json(root / "migration-report.json")
    summary = _read_json(root / "validation-summary.json")
    current = next(
        item for item in index["packages"] if item.get("id") == publication.PACKAGE_ID
    )
    assert index["generated_on"] == publication.PUBLISHED_ON
    assert current == publication._target_entry()
    assert report["generated_on"] == publication.PUBLISHED_ON
    assert report["packages"] == index["packages"]
    retained = [
        item
        for item in report["superseded_archives"]
        if publication._is_scag_retained(item)
    ]
    assert [item["version"] for item in retained] == ["1.0.1", "1.0.2"]
    assert all(
        item["superseded_by"]
        == {"version": publication.TARGET_VERSION, "checksum": publication.TARGET_CHECKSUM}
        for item in retained
    )
    assert report["counts"]["superseded_archives"] == len(
        report["superseded_archives"]
    )
    assert all(
        summary["archive_validation"][key] == value
        for key, value in _target_metrics().items()
    )
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
    (root / publication.TARGET_PATH).unlink()
    result = publication.publish(root=root, archive_builder=_builder)
    assert result["writes"] == 1
    _assert_current(root)


def test_arbitrary_old_and_new_metadata_mix_recovers(tmp_path: Path) -> None:
    root = _make_library(tmp_path)
    current_root = _make_library(tmp_path / "current", current_metadata=True)
    for name in ("migration-report.json", "validation-summary.json"):
        (root / name).write_bytes((current_root / name).read_bytes())
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


def test_packages_directory_link_outside_root_is_rejected_without_external_write(
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
    if archive_kind == "source":
        assert not (root / publication.TARGET_PATH).exists()
