"""Source-only SCAG repair tests; synthetic IO tests do not claim real rebuilding."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import zipfile
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _module(name: str):
    spec = importlib.util.spec_from_file_location(
        name, REPOSITORY_ROOT / "scripts" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


publication = _module("republish_scag_definition_checksum")
validator = _module("validate_library")


def _package() -> dict:
    return {
        "id": "synthetic",
        "version": "1",
        "content": {
            "rule_definitions": [
                {
                    "id": "example.rule",
                    "definition_checksum": "0" * 64,
                    "manifest": {"title": "Synthetic example"},
                }
            ],
            "artifacts": [
                {
                    "id": "example.artifact",
                    "rule_definition_id": "example.rule",
                    "card": {"value": 1},
                }
            ],
            "mechanics": [
                {
                    "id": "example.mechanic",
                    "rule_definition_id": "example.rule",
                    "event": "check",
                }
            ],
        },
    }


@pytest.mark.parametrize("field", ["manifest", "artifacts", "mechanics"])
def test_checksum_uses_each_exact_input_without_mutating_it(field: str) -> None:
    package = _package()
    content = package["content"]
    inputs = {
        "manifest": content["rule_definitions"][0]["manifest"],
        "artifacts": content["artifacts"],
        "mechanics": content["mechanics"],
    }
    before = copy.deepcopy(inputs)
    first = publication.definition_checksum(**inputs)
    assert inputs == before
    if field == "manifest":
        inputs[field]["title"] = "Changed"
    elif field == "artifacts":
        inputs[field][0]["card"]["value"] = 2
    else:
        inputs[field][0]["event"] = "attack"
    assert publication.definition_checksum(**inputs) != first


def test_definition_link_is_excluded_but_native_record_order_is_retained() -> None:
    inputs = {
        "manifest": {},
        "artifacts": [
            {"id": "a", "rule_definition_id": "one"},
            {"id": "b", "rule_definition_id": "one"},
        ],
        "mechanics": [],
    }
    first = publication.definition_checksum(**inputs)
    inputs["artifacts"][0]["rule_definition_id"] = "two"
    assert publication.definition_checksum(**inputs) == first
    inputs["artifacts"].reverse()
    assert publication.definition_checksum(**inputs) != first


def test_recompute_scopes_records_to_each_definition() -> None:
    package = _package()
    second = copy.deepcopy(package["content"]["rule_definitions"][0])
    second["id"] = "other.rule"
    package["content"]["rule_definitions"].append(second)
    changes = publication.recompute_definition_checksums(package)
    assert [(c["artifact_count"], c["mechanic_count"]) for c in changes] == [
        (1, 1),
        (0, 0),
    ]
    assert changes[0]["definition_checksum"] != changes[1]["definition_checksum"]


@pytest.mark.parametrize("corruption", ["checksum", "artifact", "duplicate"])
def test_validator_checks_stored_identity_and_exact_inputs(
    monkeypatch, corruption
) -> None:
    package = _package()
    changes = publication.recompute_definition_checksums(package)
    expected = {changes[0]["id"]: changes[0]["definition_checksum"]}
    monkeypatch.setattr(
        validator, "PINNED_DEFINITION_CHECKSUMS", {("synthetic", "1"): expected}
    )
    validator._validate_pinned_definitions(package, path_text="synthetic")
    if corruption == "checksum":
        package["content"]["rule_definitions"][0]["definition_checksum"] = "0" * 64
    elif corruption == "artifact":
        package["content"]["artifacts"][0]["card"]["value"] = 2
    else:
        package["content"]["rule_definitions"].append(
            copy.deepcopy(package["content"]["rule_definitions"][0])
        )
    with pytest.raises(ValueError):
        validator._validate_pinned_definitions(package, path_text="synthetic")


@pytest.fixture
def synthetic_io(tmp_path: Path, monkeypatch):
    # Deliberate IO fixture: not evidence of source-package reconstruction.
    source_bytes = b"synthetic immutable input"
    target_bytes = b"synthetic corrected output"
    for prefix, data in (("SOURCE", source_bytes), ("TARGET", target_bytes)):
        monkeypatch.setattr(publication, f"{prefix}_ARCHIVE_SIZE", len(data))
        monkeypatch.setattr(
            publication, f"{prefix}_ARCHIVE_SHA256", hashlib.sha256(data).hexdigest()
        )
    calls = []

    def builder(data):
        assert data == source_bytes
        calls.append(data)
        return target_bytes

    monkeypatch.setattr(publication, "_build_target_archive", builder)
    source = tmp_path / "source.pack"
    output = tmp_path / "corrected.pack"
    source.write_bytes(source_bytes)
    return source, output, source_bytes, target_bytes, calls


def test_local_output_and_repeat_preserve_input_and_metadata(synthetic_io) -> None:
    source, output, source_bytes, target_bytes, calls = synthetic_io
    evidence = source.parent / "import-evidence.json"
    evidence.write_bytes(b'{"observed": "old input only"}')
    first = publication.repair_local_archive(source=source, output=output)
    second = publication.repair_local_archive(source=source, output=output)
    assert (first["status"], second["status"]) == ("created", "already_present")
    assert first["published"] is False and first["import_verified"] is False
    assert len(calls) == 2
    assert source.read_bytes() == source_bytes
    assert output.read_bytes() == target_bytes
    assert evidence.read_bytes() == b'{"observed": "old input only"}'
    assert not list(source.parent.glob(".scag-repair-*.tmp"))


def test_invalid_source_is_rejected_before_build_or_write(synthetic_io) -> None:
    source, output, _, _, calls = synthetic_io
    source.write_bytes(b"changed")
    with pytest.raises(publication.PublicationConflictError, match="exact finalized"):
        publication.repair_local_archive(source=source, output=output)
    assert not output.exists() and calls == []


def test_builder_drift_is_rejected_before_write(synthetic_io, monkeypatch) -> None:
    source, output, *_ = synthetic_io
    monkeypatch.setattr(publication, "_build_target_archive", lambda _: b"wrong output")
    with pytest.raises(publication.PublicationConflictError, match="archive conflicts"):
        publication.repair_local_archive(source=source, output=output)
    assert not output.exists()


def test_conflicting_output_is_never_overwritten(synthetic_io) -> None:
    source, output, *_ = synthetic_io
    output.write_bytes(b"user data")
    with pytest.raises(publication.PublicationConflictError, match="different content"):
        publication.repair_local_archive(source=source, output=output)
    assert output.read_bytes() == b"user data"


def test_output_race_does_not_overwrite_competing_file(
    synthetic_io, monkeypatch
) -> None:
    source, output, *_ = synthetic_io
    real_link = publication.os.link

    def competing_writer(src, dst):
        Path(dst).write_bytes(b"concurrent user data")
        return real_link(src, dst)

    monkeypatch.setattr(publication.os, "link", competing_writer)
    with pytest.raises(FileExistsError):
        publication.repair_local_archive(source=source, output=output)
    assert output.read_bytes() == b"concurrent user data"
    assert not list(source.parent.glob(".scag-repair-*.tmp"))


@pytest.mark.parametrize("failure", ["fsync", "link"])
def test_output_failure_leaves_no_partial_destination(
    synthetic_io, monkeypatch, failure
) -> None:
    source, output, source_bytes, *_ = synthetic_io

    def fail(*_args):
        raise OSError("injected write failure")

    monkeypatch.setattr(publication.os, failure, fail)
    with pytest.raises(OSError, match="injected"):
        publication.repair_local_archive(source=source, output=output)
    assert source.read_bytes() == source_bytes
    assert not output.exists()
    assert not list(source.parent.glob(".scag-repair-*.tmp"))


@pytest.mark.parametrize("target", ["source", "parent"])
def test_link_or_reparse_detection_prevents_writes(
    synthetic_io, monkeypatch, target
) -> None:
    source, output, _, _, calls = synthetic_io
    linked = source if target == "source" else output.parent
    monkeypatch.setattr(publication, "_is_reparse_point", lambda p: p == linked)
    with pytest.raises(publication.PublicationConflictError, match="reparse"):
        publication.repair_local_archive(source=source, output=output)
    assert calls == [] and not output.exists()


def test_same_input_output_and_repository_destination_are_rejected(
    synthetic_io,
) -> None:
    source, output, _, _, calls = synthetic_io
    for destination in (source, REPOSITORY_ROOT / "content-library" / output.name):
        with pytest.raises(publication.PublicationConflictError):
            publication.repair_local_archive(source=source, output=destination)
    assert calls == [] and not output.exists()


def test_traversal_is_rejected(synthetic_io) -> None:
    source, output, *_ = synthetic_io
    with pytest.raises(publication.PublicationConflictError, match="traversal"):
        publication.repair_local_archive(
            source=source, output=output.parent / ".." / output.name
        )
    assert not output.exists()


def test_cli_requires_explicit_paths_without_writing(capsys) -> None:
    with pytest.raises(SystemExit) as error:
        publication.main([])
    assert error.value.code == 2
    assert "--source" in capsys.readouterr().err


def test_real_authorized_archive_rebuild_and_input_integrity(tmp_path: Path) -> None:
    configured = os.environ.get("SAGASMITH_SCAG_SOURCE_ARCHIVE")
    if not configured:
        pytest.skip("explicit authorized SCAG source is not configured")
    # Once explicitly configured, missing dependencies/files or a bad hash FAIL.
    source = Path(configured)
    source_bytes = source.read_bytes()
    output = tmp_path / "repaired.sagasmith-pack"
    result = publication.repair_local_archive(source=source, output=output)
    assert result["archive_sha256"] == publication.TARGET_ARCHIVE_SHA256
    assert source.read_bytes() == source_bytes
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(output) as new:
        before = json.loads(old.read("package.sagasmith.json"))
        after = json.loads(new.read("package.sagasmith.json"))
        assert old.namelist() == new.namelist()
        for name in old.namelist():
            if name != "package.sagasmith.json":
                assert old.read(name) == new.read(name)
    assert after["content"]["artifacts"] == before["content"]["artifacts"]
    assert after["content"]["mechanics"] == before["content"]["mechanics"]
    changes = publication.recompute_definition_checksums(copy.deepcopy(after))
    assert len(changes) == 1
    assert changes[0]["source_definition_checksum"] == changes[0]["definition_checksum"]
    assert changes[0]["definition_checksum"] == publication.TARGET_DEFINITION_CHECKSUM
    normalized = copy.deepcopy(after)
    normalized["version"] = before["version"]
    normalized["checksum"] = before["checksum"]
    normalized["manifest"]["version"] = before["manifest"]["version"]
    normalized["metadata"].pop("definition_checksum_correction")
    normalized["content"]["rule_definitions"][0]["definition_checksum"] = (
        publication.SOURCE_DEFINITION_CHECKSUM
    )
    assert normalized == before
