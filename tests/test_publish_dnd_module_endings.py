"""Regression tests for evidence-bound ending publication."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.publish_dnd_module_endings import (
    TARGETS,
    _prepare_package,
    _source_chunk,
)


def _fixture_package(package_id: str) -> dict:
    target = TARGETS[package_id]
    chunks = [
        {
            "key": target["chunk_key"],
            "content_hash": target["chunk_hash"],
            "page_start": target["page"],
            "page_end": target["page"],
        }
    ]
    if "supporting_source" in target:
        supporting = target["supporting_source"]
        chunks.append(
            {
                "key": supporting["chunk_key"],
                "content_hash": supporting["chunk_hash"],
                "page_start": supporting["page"],
                "page_end": supporting["page"],
            }
        )
    return {
        "id": package_id,
        "version": "1.0.1",
        "content": {"narrative": {"dossiers": [], "endings": []}},
        "sources": [
            {
                "source_key": target["source_key"],
                "sections": [
                    {
                        "chunks": chunks
                    }
                ],
            }
        ],
    }


@pytest.mark.parametrize("package_id", sorted(TARGETS))
def test_each_target_has_one_evidence_bound_ending(package_id: str) -> None:
    package = _fixture_package(package_id)
    published = _prepare_package(package, TARGETS[package_id])
    endings = published["content"]["narrative"]["endings"]
    assert len(endings) == 1
    ending = endings[0]
    if "supporting_source" in TARGETS[package_id]:
        refs = ending["source_refs"]
        assert {ref["chunk_key"] for ref in refs} == {
            TARGETS[package_id]["chunk_key"],
            TARGETS[package_id]["supporting_source"]["chunk_key"],
        }
    else:
        refs = [ending["source_ref"]]
    assert all(ref["source_key"] == TARGETS[package_id]["source_key"] for ref in refs)


@pytest.mark.parametrize("package_id", sorted(TARGETS))
def test_publication_is_idempotent(package_id: str) -> None:
    target = TARGETS[package_id]
    first = _prepare_package(_fixture_package(package_id), target)
    second = _prepare_package(first, target)
    assert second == first


@pytest.mark.parametrize("package_id", sorted(TARGETS))
def test_source_digest_drift_fails_closed(package_id: str) -> None:
    package = _fixture_package(package_id)
    package["sources"][0]["sections"][0]["chunks"][0]["content_hash"] = "0" * 64
    with pytest.raises(ValueError, match="terminal source digest drift"):
        _source_chunk(package, TARGETS[package_id])


def test_current_archives_are_replaced_without_old_versions() -> None:
    root = Path(__file__).resolve().parents[1] / "content-library"
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in index["packages"]}
    for package_id in TARGETS:
        item = by_id[package_id]
        assert item["version"] == "1.0.2"
        archive = root / item["path"]
        assert archive.is_file()
        with zipfile.ZipFile(archive) as handle:
            package = json.loads(handle.read("package.sagasmith.json"))
        assert package["version"] == "1.0.2"
        assert len(package["content"]["narrative"]["endings"]) == 1
