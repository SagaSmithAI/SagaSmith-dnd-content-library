"""Publish source-bound endings for the four current terminal-less D&D Packs.

The current archives are immutable.  This script creates one replacement
version per target, updates the current catalog, and records each superseded
archive in the migration report.  It deliberately refuses source or catalog
drift so a rerun cannot silently attach an ending to a different corpus.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1] / "content-library"
PACKAGE_ROOT = ROOT / "packages"
TODAY = "2026-09-01"

LM_SOURCE_KEY = "c3095b66e2f6-Lost-Mine-of-Phandelver.pdf"
LM_CONCLUSION_CHUNK = (
    f"{LM_SOURCE_KEY}/scene/part-4-wave-echo-cave-conclusion/"
    "chunk/0-ea475606d2d564305a5fe47c"
)
WATERDEEP_SOURCE_KEY = "8f582d64c01c-D-D-5E---Waterdeep---Dragon-Heist.pdf"
WATERDEEP_CONCLUSION_CHUNK = (
    f"{WATERDEEP_SOURCE_KEY}/scene/ch-4-dragon-season-converted-windmill/"
    "chunk/68-10ed09cce12d525f6b3ac669"
)
WATERDEEP_CONTINUATION_CHUNK = (
    f"{WATERDEEP_SOURCE_KEY}/scene/ch-4-dragon-season-converted-windmill/"
    "chunk/72-6d9385cbe14ca333675fe90b"
)

LM_EXCERPT = (
    "With hard work and a little luck, the adventurers have defeated the Black "
    "Spider and undone his destructive plots, cleared Phandalin of the ruffians "
    "who threatened its people, and reclaimed the lost mine of Wave Echo Cave."
)
WATERDEEP_EXCERPT = (
    "The adventure could play out in any of several ways, depending on who gets "
    "the gold and what's done with the treasure."
)

TARGETS: dict[str, dict[str, Any]] = {
    "906e1c57-005d-4bf1-8b03-221e0726e27d": {
        "source_version": "1.0.0",
        "source_checksum": "474e0fb3e0576ac879467f88d3543142d921040759cf85ed776eea6864c3999f",
        "source_key": LM_SOURCE_KEY,
        "chunk_key": LM_CONCLUSION_CHUNK,
        "chunk_hash": "ea475606d2d564305a5fe47cd638b52971640e2e79fad22a5b5cb6399a5999e2",
        "page": 51,
        "ending": {
            "conditions": [
                "Black Spider defeated",
                "Phandalin cleared of the ruffians",
                "Wave Echo Cave reclaimed",
                "party reaches 5th level",
            ],
            "consequences": [
                "Gundren and Nundro administer the restored mine",
                "the party receives a 10 percent share of the mine's profits",
                "the party may continue into new adventures",
            ],
            "excerpt": LM_EXCERPT,
            "id": "wave-echo-conclusion",
            "status": "legal_complete",
            "title": "Wave Echo Cave conclusion",
            "trigger": "resolve the source-declared Wave Echo Cave conclusion",
        },
    },
    "d0871484-131a-418f-aba3-016e944411ab": {
        "source_version": "1.0.0",
        "source_checksum": "7d986826e2274337e0473327f2d33c3b26c7c456533b0364d3335cf34acba75d",
        "source_key": LM_SOURCE_KEY,
        "chunk_key": LM_CONCLUSION_CHUNK,
        "chunk_hash": "ea475606d2d564305a5fe47cd638b52971640e2e79fad22a5b5cb6399a5999e2",
        "page": 51,
        "ending": {
            "conditions": [
                "Black Spider defeated",
                "Phandalin cleared of the ruffians",
                "Wave Echo Cave reclaimed",
                "party reaches 5th level",
            ],
            "consequences": [
                "Gundren and Nundro administer the restored mine",
                "the party receives a 10 percent share of the mine's profits",
                "the party may continue into new adventures",
            ],
            "excerpt": LM_EXCERPT,
            "id": "wave-echo-conclusion",
            "status": "legal_complete",
            "title": "Wave Echo Cave conclusion",
            "trigger": "resolve the source-declared Wave Echo Cave conclusion",
        },
    },
    "dnd5e.module.lost-mine-of-phandelver.full-agent-corpus-v12": {
        "source_version": "1.0.0",
        "source_checksum": "ae2d5f7e01cad31d96c30a6e96f0c5427f8a2efa07feeb95d98b5b45dfea8855",
        "source_key": LM_SOURCE_KEY,
        "chunk_key": LM_CONCLUSION_CHUNK,
        "chunk_hash": "ea475606d2d564305a5fe47cd638b52971640e2e79fad22a5b5cb6399a5999e2",
        "page": 51,
        "ending": {
            "conditions": [
                "Black Spider defeated",
                "Phandalin cleared of the ruffians",
                "Wave Echo Cave reclaimed",
                "party reaches 5th level",
            ],
            "consequences": [
                "Gundren and Nundro administer the restored mine",
                "the party receives a 10 percent share of the mine's profits",
                "the party may continue into new adventures",
            ],
            "excerpt": LM_EXCERPT,
            "id": "wave-echo-conclusion",
            "status": "legal_complete",
            "title": "Wave Echo Cave conclusion",
            "trigger": "resolve the source-declared Wave Echo Cave conclusion",
        },
    },
    "dnd5e.module.waterdeep-dragon-heist": {
        "source_version": "1.0.0",
        "source_checksum": "848c7df8f5129c8a5aa774675adebcb454577f3125ad07f691accdd4bb40c521",
        "source_key": WATERDEEP_SOURCE_KEY,
        "chunk_key": WATERDEEP_CONCLUSION_CHUNK,
        "chunk_hash": "10ed09cce12d525f6b3ac669b3d188c7909defcee1eb10b09938197525666db2",
        "page": 99,
        "supporting_source": {
            "chunk_key": WATERDEEP_CONTINUATION_CHUNK,
            "chunk_hash": "6d9385cbe14ca333675fe90bbe2929cd10cfaf2cc631a4a297ca98c5f3dddc4b",
            "page": 99,
        },
        "ending": {
            "conditions": [
                "Vault of Dragons conflict resolved",
                "the fate of Neverember's hoard is determined",
                "party reaches 5th level",
            ],
            "consequences": [
                "the adventure resolves according to who gets the gold and what is done with it",
                "the party may continue toward Undermountain",
            ],
            "excerpt": WATERDEEP_EXCERPT,
            "id": "adventure-conclusion",
            "status": "legal_complete",
            "title": "Adventure Conclusion",
            "trigger": "resolve the source-declared Adventure Conclusion after the Vault of Dragons",
        },
    },
}


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _write_object(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _next_patch(version: str) -> str:
    parts = version.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f"cannot bump non-semantic version: {version}")
    major, minor, patch = (int(part) for part in parts)
    return f"{major}.{minor}.{patch + 1}"


def _source_chunk(package: Mapping[str, Any], target: Mapping[str, Any]) -> dict[str, Any]:
    sources = list(package.get("sources") or [])
    if len(sources) != 1 or sources[0].get("source_key") != target["source_key"]:
        raise ValueError(f"source identity drift for {package.get('id')}")
    matches = [
        chunk
        for section in list(sources[0].get("sections") or [])
        for chunk in list(section.get("chunks") or [])
        if chunk.get("key") == target["chunk_key"]
    ]
    if len(matches) != 1:
        raise ValueError(f"terminal source chunk drift for {package.get('id')}")
    chunk = matches[0]
    if chunk.get("content_hash") != target["chunk_hash"]:
        raise ValueError(f"terminal source digest drift for {package.get('id')}")
    if chunk.get("page_start") != target["page"] or chunk.get("page_end") != target["page"]:
        raise ValueError(f"terminal source page drift for {package.get('id')}")
    return chunk


def expected_ending(package: Mapping[str, Any], target: Mapping[str, Any]) -> dict[str, Any]:
    """Build an ending from verified source metadata without inventing a locator."""

    chunk = _source_chunk(package, target)
    ending = copy.deepcopy(dict(target["ending"]))
    source_ref = {
        "chunk_key": str(chunk["key"]),
        "note": f"Agent-reviewed source evidence: {target['source_key']} / page {target['page']}",
        "page": int(chunk["page_start"]),
        "source_key": target["source_key"],
    }
    supporting = target.get("supporting_source")
    if supporting is None:
        ending["source_ref"] = source_ref
    else:
        support_chunk = _source_chunk(
            package,
            {
                **target,
                "chunk_key": supporting["chunk_key"],
                "chunk_hash": supporting["chunk_hash"],
                "page": supporting["page"],
            },
        )
        ending["source_refs"] = [
            source_ref,
            {
                "chunk_key": str(support_chunk["key"]),
                "note": f"Agent-reviewed source evidence: {target['source_key']} / page {supporting['page']}",
                "page": int(support_chunk["page_start"]),
                "source_key": target["source_key"],
            },
        ]
    return ending


def _prepare_package(package: Mapping[str, Any], target: Mapping[str, Any]) -> dict[str, Any]:
    candidate = copy.deepcopy(dict(package))
    narrative = dict(candidate.get("content", {}).get("narrative") or {})
    endings = list(narrative.get("endings") or [])
    ending = expected_ending(candidate, target)
    if endings:
        if len(endings) == 1 and endings[0] == ending:
            return candidate
        raise ValueError(f"unexpected existing endings for {candidate.get('id')}")
    narrative["endings"] = [ending]
    narrative.setdefault("dossiers", [])
    candidate["content"]["narrative"] = narrative
    return candidate


def main() -> None:
    from sagasmith_core.content_pack import dumps_content_archive, loads_content_archive

    index_path = ROOT / "index.json"
    report_path = ROOT / "migration-report.json"
    summary_path = ROOT / "validation-summary.json"
    index = _read_object(index_path)
    report = _read_object(report_path)
    summary = _read_object(summary_path)
    packages = list(index.get("packages") or [])
    by_id = {str(item.get("id") or ""): item for item in packages if isinstance(item, dict)}
    if set(by_id) & set(TARGETS) != set(TARGETS):
        raise ValueError("one or more target Packs are absent from the current index")

    replacements: dict[str, dict[str, Any]] = {}
    old_paths: list[Path] = []
    superseded = list(report.get("superseded_archives") or [])
    for package_id in sorted(TARGETS):
        item = dict(by_id[package_id])
        target = TARGETS[package_id]
        if item.get("source_version") != target["source_version"] or item.get("source_checksum") != target["source_checksum"]:
            raise ValueError(f"source identity drift for indexed Pack {package_id}")
        old_path = (ROOT / str(item["path"])).resolve()
        if old_path.parent != PACKAGE_ROOT.resolve() or not old_path.is_file():
            raise ValueError(f"target archive is outside packages/: {item['path']}")
        package, blobs = loads_content_archive(old_path.read_bytes())
        if any(package.get(field) != item.get(field) for field in ("id", "version", "checksum", "system_id", "kind")):
            raise ValueError(f"target archive identity is stale: {package_id}")
        if str(item["version"]) != target.get("current_version", "1.0.1"):
            if item.get("action") == "published_source_bound_ending" and _prepare_package(package, target)["content"]["narrative"]["endings"]:
                replacements[package_id] = item
                continue
            raise ValueError(f"unexpected current version for {package_id}")
        candidate = _prepare_package(package, target)
        from sagasmith_core.content_pack import build_content_package
        from sagasmith_dnd.content_packages import (
            canonicalize_dnd_content_package,
            validate_dnd_content_package,
        )
        canonical = canonicalize_dnd_content_package(candidate)
        rebuilt = build_content_package(
            kind=str(canonical["kind"]), package_id=str(canonical["id"]), version=_next_patch(str(item["version"])),
            system_id=str(canonical["system_id"]), manifest=canonical["manifest"], dependencies=canonical["dependencies"],
            sources=canonical["sources"], assets=canonical["assets"], content_reviews=canonical["content_reviews"],
            actors=canonical["actors"], content=canonical["content"], metadata=canonical["metadata"],
        )
        rebuilt = validate_dnd_content_package(rebuilt)
        archive = dumps_content_archive(rebuilt, blobs)
        filename = f"{rebuilt['checksum'][:12]}-{rebuilt['id']}-{rebuilt['version']}.sagasmith-pack"
        new_path = (PACKAGE_ROOT / filename).resolve()
        if new_path == old_path or (new_path.exists() and new_path.read_bytes() != archive):
            raise ValueError(f"replacement archive path collision for {package_id}")
        new_path.write_bytes(archive)
        replacements[package_id] = {
            **item,
            "action": "published_source_bound_ending",
            "version": str(rebuilt["version"]),
            "checksum": str(rebuilt["checksum"]),
            "archive_sha256": hashlib.sha256(archive).hexdigest(),
            "archive_size": len(archive),
            "source_path": str(item["path"]),
            "path": f"packages/{filename}",
        }
        old_paths.append(old_path)
        superseded.append({"identity": [item["system_id"], item["kind"], item["id"]], "version": item["version"], "checksum": item["checksum"], "path": item["path"]})

    updated = [replacements.get(str(item.get("id") or ""), item) for item in packages]
    index["generated_on"] = TODAY
    index["packages"] = updated
    report["generated_on"] = TODAY
    report["packages"] = updated
    report["superseded_archives"] = superseded
    report.setdefault("counts", {})["superseded_archives"] = len(superseded)
    archive_validation = dict(summary.get("archive_validation") or {})
    current_bytes = sum((ROOT / str(item["path"])).stat().st_size for item in updated)
    retained_count = int(archive_validation.get("retained_superseded_archives", 0))
    retained_bytes = int(archive_validation.get("retained_superseded_bytes", 0))
    archive_validation.update(
        {
            "archives": len(updated),
            "bytes": current_bytes,
            "stored_archives": len(updated) + retained_count,
            "stored_bytes": current_bytes + retained_bytes,
        }
    )
    summary["archive_validation"] = archive_validation
    _write_object(index_path, index)
    _write_object(report_path, report)
    _write_object(summary_path, summary)
    for old_path in old_paths:
        old_path.unlink()
    print(json.dumps({"published": len(old_paths), "packages": sorted(replacements)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
