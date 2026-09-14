"""Publish the immutable, source-corrected Tortle Package archive."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1] / "content-library"
PACKAGE_ID = "dnd5e.addon.rulebook.d-d-5e-the-tortle-package.e3234de670da.addon"
RULE_DEFINITION_ID = PACKAGE_ID.removesuffix(".addon")
SOURCE_VERSION = "1.0.1"
SOURCE_CHECKSUM = "356cbf231ea7ecf8dab48b7cca127523d1d0bd3f5b5535899f45641f24bc5759"
SOURCE_ARCHIVE_SHA256 = "c61d41ec634f2ba130802ea2505a40dba0c24fb79d7ea9a22629fdd9f3849747"
SOURCE_ARCHIVE_SIZE = 178781
TARGET_VERSION = "1.0.2"
# Filled after the deterministic archive is built; keeping these explicit makes
# a rerun fail closed if the reviewed source or correction changes.
TARGET_CHECKSUM = "b5010b3860ee25ea80aa0ae703644e985ddc418ef81e26f658cceb8e12b3872e"
TARGET_ARCHIVE_SHA256 = "37c46087480dc91db14f65b746d994c8b549bc1b48b26f35c25e6a88d7207c02"
TARGET_ARCHIVE_SIZE = 179280
PUBLISHED_ON = "2026-09-10"
SOURCE_PATH = (
    "packages/356cbf231ea7-dnd5e.addon.rulebook."
    "d-d-5e-the-tortle-package.e3234de670da.addon-1.0.1.sagasmith-pack"
)
TARGET_PATH = (
    "packages/{checksum}-dnd5e.addon.rulebook."
    "d-d-5e-the-tortle-package.e3234de670da.addon-1.0.2.sagasmith-pack"
)
TORTLE_ID = f"{RULE_DEFINITION_ID}.species.tortle"
SOURCE_KEY = "user.rulebook.d-d-5e-the-tortle-package.e3234de670"
AC_MECHANIC_ID = "dnd5e.core.ac.tortle_natural_armor"
SHELL_MECHANIC_ID = "dnd5e.core.activity.tortle_shell_defense"
MECHANIC_REFS = [AC_MECHANIC_ID, SHELL_MECHANIC_ID]


class PublicationConflictError(RuntimeError):
    """Raised before writes when an archive or metadata identity conflicts."""


class InjectedPublicationFailure(RuntimeError):
    """Test-only failure injected after an atomic replacement."""


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _object_bytes(value: dict[str, Any], *, newline: bytes) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8").replace(
        b"\n", newline
    )


def _newline_for(content: bytes) -> bytes:
    return b"\r\n" if b"\r\n" in content else b"\n"


def _is_link(path: Path) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_symlink():
        return True
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except OSError as error:
        raise PublicationConflictError(f"cannot inspect path: {path}") from error


def _safe_archive_path(root: Path, relative: str) -> Path:
    if "\\" in relative or Path(relative).is_absolute():
        raise PublicationConflictError(f"unsafe archive path: {relative!r}")
    parts = relative.split("/")
    if len(parts) != 2 or parts[0] != "packages" or not parts[1]:
        raise PublicationConflictError(f"unsafe archive path: {relative!r}")
    packages = root / "packages"
    if _is_link(packages) or not packages.is_dir() or packages.resolve() != packages:
        raise PublicationConflictError("packages/ must be a real directory")
    path = root / relative
    if _is_link(path) or path.resolve().parent != packages.resolve():
        raise PublicationConflictError(f"archive path escapes packages/: {relative!r}")
    return path.resolve()


def _find_artifact(artifacts: list[dict[str, Any]], artifact_id: str) -> dict[str, Any]:
    matches = [item for item in artifacts if item.get("id") == artifact_id]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one artifact {artifact_id!r}")
    return matches[0]


def _source_chunks(
    package: dict[str, Any], blobs: dict[str, bytes]
) -> tuple[dict[str, Any], list[tuple[dict[str, Any], str]], str]:
    sources = list(package.get("sources") or [])
    source = next((item for item in sources if item.get("source_key") == SOURCE_KEY), None)
    if source is None:
        raise ValueError("Tortle source bundle is missing")
    asset_key = str(source.get("normalized_document_asset_key") or "")
    assets = [item for item in package.get("assets") or [] if item.get("asset_key") == asset_key]
    if len(assets) != 1:
        raise ValueError("Tortle normalized source asset is missing or ambiguous")
    normalized = blobs[str(assets[0]["checksum"])].decode("utf-8")
    sections = [item for item in source.get("sections") or [] if item.get("ordinal") == 9]
    if len(sections) != 1:
        raise ValueError("Tortle traits must remain section 9")
    section = sections[0]
    chunks = list(section.get("chunks") or [])
    if len(chunks) != 2:
        raise ValueError("Tortle traits must retain chunks 10 and 11")
    chunks.sort(key=lambda item: int(item["start_offset"]))
    merged_parts: list[str] = []
    cursor = int(section["start_offset"])
    result: list[tuple[dict[str, Any], str]] = []
    for chunk in chunks:
        start, end = int(chunk["start_offset"]), int(chunk["end_offset"])
        if start < cursor or end <= start:
            # Overlap is expected for chunks 10/11, but contradictory offsets
            # are not accepted.
            if end <= cursor or end <= start:
                raise ValueError("Tortle source chunk offsets are invalid")
        text = normalized[start:end]
        result.append((chunk, text))
        merged_parts.append(normalized[max(cursor, start) : end])
        cursor = max(cursor, end)
    merged = "".join(merged_parts)
    expected = normalized[int(section["start_offset"]) : int(section["end_offset"])]
    if merged != expected:
        raise ValueError("Tortle chunk merge does not reproduce indexed section 9")
    if "\n\nnormal. Shell Defense." in merged:
        raise ValueError("Tortle chunk merge retained the known duplicate overlap")
    return source, result, merged


def _source_ref(chunk: dict[str, Any], *, note: str) -> dict[str, Any]:
    return {
        "chunk_key": str(chunk["key"]),
        "note": note,
        "page": int(chunk["page_start"]),
        "source_key": SOURCE_KEY,
    }


def _rule_ref(chunk: dict[str, Any]) -> str:
    return f"rule-source:{SOURCE_KEY}#chunk:{chunk['key']}"


def _source_citation(chunk: dict[str, Any], text: str) -> dict[str, Any]:
    return {
        "source": f"rule-source:{SOURCE_KEY}",
        "source_excerpt": text,
        "source_ref": {"chunk_key": str(chunk["key"])},
    }


def _review_artifact(artifact: dict[str, Any], references: list[str]) -> None:
    from sagasmith_dnd.content_validation import build_catalog_review, build_selection_contract

    old_contract = dict(artifact["selection_contract"])
    artifact["selection_contract"] = build_selection_contract(
        artifact,
        status=str(old_contract["status"]),
        materializer=str(old_contract["materializer"]),
        references=references,
        blockers=list(old_contract["blockers"]),
    )
    artifact["catalog_review"] = build_catalog_review(
        artifact,
        decisions=copy.deepcopy(artifact["catalog_review"]["decisions"]),
        status="approved",
    )


def _correct_package(package: dict[str, Any], blobs: dict[str, bytes]) -> dict[str, Any]:
    from sagasmith_core.content_pack import build_content_package
    from sagasmith_dnd.content_packages import validate_dnd_content_package

    if (
        package.get("id") != PACKAGE_ID
        or package.get("version") != SOURCE_VERSION
        or package.get("checksum") != SOURCE_CHECKSUM
    ):
        raise ValueError("Tortle source archive is not the reviewed 1.0.1 package")
    corrected = copy.deepcopy(package)
    source, chunks, merged = _source_chunks(corrected, blobs)
    chunk_values = [chunk for chunk, _text in chunks]
    refs = [_rule_ref(chunk) for chunk in chunk_values]
    source_refs = [_source_ref(chunk, note="Tortle traits source evidence") for chunk in chunk_values]
    artifact = _find_artifact(corrected["content"]["artifacts"], TORTLE_ID)
    if artifact.get("kind") != "species" or artifact.get("application_state") != "selection_ready":
        raise ValueError("Tortle artifact must remain a selection-ready species")
    artifact["mechanic_refs"] = list(MECHANIC_REFS)
    card = artifact["card"]
    card["description"] = merged
    card["mechanic_refs"] = list(MECHANIC_REFS)
    ruling_requirements = list(card.get("ruling_requirements") or [])
    if len(ruling_requirements) != 1:
        raise ValueError("Tortle card must retain one source-bound ruling")
    ruling_requirements[0]["source_excerpt"] = merged
    card["ruling_requirements"] = ruling_requirements
    for feature in card["grants"]["features"]:
        name = str(feature.get("name") or "")
        if name == "Natural Armor":
            feature["mechanic_refs"] = [AC_MECHANIC_ID]
            feature["choices"] = {
                "source_trait": {
                    "kind": "tortle_natural_armor",
                    "base_ac": 17,
                    "includes_dexterity": False,
                    "armor_benefit": "none",
                    "allows_shield": True,
                    "source_excerpt": "Your shell provides ample protection, however; it gives you a base AC of 17 (your Dexterity modifier doesn't affect this number). You gain no benefit from wearing armor, but if you are using a shield, you can apply the shield's bonus as normal.",
                }
            }
        elif name == "Shell Defense":
            feature["mechanic_refs"] = [SHELL_MECHANIC_ID]
            feature["choices"] = {
                "standard_resolution": {
                    "kind": "tortle_shell_defense",
                    "activation": "action",
                    "emerge": "bonus_action",
                    "duration": "until_emerges",
                    "effects": {
                        "ac_bonus": 4,
                        "saving_throw_advantage": ["strength", "constitution"],
                        "condition_add": ["prone"],
                        "speed": 0,
                        "speed_can_increase": False,
                        "dexterity_save_disadvantage": True,
                        "reactions": False,
                        "only_action": "bonus_action_emerge",
                    },
                    "source_refs": list(refs),
                }
            }
    clause = list(artifact.get("rule_clauses") or [])
    if len(clause) != 1:
        raise ValueError("Tortle card must retain one source-bound rule clause")
    clause[0]["source_citations"] = [_source_citation(chunk, text) for chunk, text in chunks]
    artifact["rule_clauses"] = clause
    artifact["rule_refs"] = list(refs)
    artifact["source_refs"] = source_refs
    _review_artifact(artifact, [f"rule-source-chunk:{chunk['key']}" for chunk in chunk_values])
    manifest = copy.deepcopy(corrected["manifest"])
    manifest["native_mechanic_refs"] = list(MECHANIC_REFS)
    metadata = copy.deepcopy(corrected["metadata"])
    metadata["source_correction"] = {
        "schema": "sagasmith.pack-source-correction.v1",
        "source_version": SOURCE_VERSION,
        "source_checksum": SOURCE_CHECKSUM,
        "updated_on": PUBLISHED_ON,
        "changes": [
            "deduplicated the 180-character overlap between Tortle traits chunks 10 and 11",
            "bound Natural Armor and Shell Defense to the reviewed core mechanics",
            "persisted the complete Shell Defense action and effect contract with both source refs",
        ],
    }
    rebuilt = build_content_package(
        kind=str(corrected["kind"]),
        package_id=PACKAGE_ID,
        version=TARGET_VERSION,
        system_id=str(corrected["system_id"]),
        manifest=manifest,
        dependencies=corrected["dependencies"],
        sources=corrected["sources"],
        assets=corrected["assets"],
        content_reviews=corrected["content_reviews"],
        actors=corrected["actors"],
        content=corrected["content"],
        metadata=metadata,
    )
    return validate_dnd_content_package(rebuilt)


def _build_target_archive(source_bytes: bytes) -> bytes:
    from sagasmith_core.content_pack import dumps_content_archive, loads_content_archive

    package, blobs = loads_content_archive(source_bytes)
    return dumps_content_archive(_correct_package(package, blobs), blobs)


def _entry(version: str, checksum: str, archive_sha256: str, archive_size: int, path: str, *, action: str, source_version: str, source_checksum: str, source_path: str) -> dict[str, Any]:
    return {
        "system_id": "dnd5e", "kind": "addon", "id": PACKAGE_ID,
        "action": action, "source_version": source_version, "source_checksum": source_checksum,
        "version": version, "checksum": checksum, "archive_sha256": archive_sha256,
        "archive_size": archive_size, "source_path": source_path, "path": path,
        "dependencies": [], "provided_rule_definitions": [{"id": RULE_DEFINITION_ID, "version": "1.0.0"}],
        "runtime_rule_dependencies": [{"checksum": "3f7508a4177c3dd4a9678d55d55d67a48c282a17f03a0943e092de486f850670", "id": "dnd5e.content.srd2014", "version": "1.24.0"}],
    }


def _desired_metadata(index: dict[str, Any], report: dict[str, Any], summary: dict[str, Any], evidence: dict[str, Any], target_path: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    current = _entry(SOURCE_VERSION, SOURCE_CHECKSUM, SOURCE_ARCHIVE_SHA256, SOURCE_ARCHIVE_SIZE, SOURCE_PATH, action="migrated", source_version="1.0.0", source_checksum="f95434549028ea51648dfa7ccba5aa120bfb3ab54d6022975b890e4927531ab4", source_path="tmp/unified-current-packs-all-v3/d-d-5e-the-tortle-package-e3234de670.sagasmith-pack")
    target = _entry(TARGET_VERSION, TARGET_CHECKSUM, TARGET_ARCHIVE_SHA256, TARGET_ARCHIVE_SIZE, target_path, action="source_corrected_current", source_version=SOURCE_VERSION, source_checksum=SOURCE_CHECKSUM, source_path=SOURCE_PATH)
    for values, field in ((index.get("packages"), "index.packages"), (report.get("packages"), "migration-report.packages")):
        if not isinstance(values, list) or sum(item.get("id") == PACKAGE_ID for item in values if isinstance(item, dict)) != 1:
            raise PublicationConflictError(f"{field} must contain exactly one Tortle package")
        entry = next(item for item in values if item.get("id") == PACKAGE_ID)
        if entry not in (current, target):
            raise PublicationConflictError(f"{field} Tortle metadata conflicts")
    retained = report.get("superseded_archives")
    if not isinstance(retained, list):
        raise PublicationConflictError("migration-report.superseded_archives must be a list")
    tortle_retained = [item for item in retained if (item.get("identity") or [None, None, None])[2] == PACKAGE_ID]
    old_retained = {"identity": ["dnd5e", "addon", PACKAGE_ID], "version": SOURCE_VERSION, "checksum": SOURCE_CHECKSUM, "path": SOURCE_PATH, "archive_sha256": SOURCE_ARCHIVE_SHA256, "archive_size": SOURCE_ARCHIVE_SIZE, "retained_finalized": True, "superseded_by": {"version": TARGET_VERSION, "checksum": TARGET_CHECKSUM}}
    if tortle_retained not in ([], [old_retained]):
        raise PublicationConflictError("Tortle retained metadata conflicts")
    desired_index = copy.deepcopy(index); desired_index["generated_on"] = PUBLISHED_ON
    desired_index["packages"] = [target if item.get("id") == PACKAGE_ID else item for item in index["packages"]]
    desired_report = copy.deepcopy(report); desired_report["generated_on"] = PUBLISHED_ON; desired_report["packages"] = copy.deepcopy(desired_index["packages"])
    desired_report["superseded_archives"] = [item for item in retained if (item.get("identity") or [None, None, None])[2] != PACKAGE_ID] + [old_retained]
    desired_report["counts"]["superseded_archives"] = len(desired_report["superseded_archives"])
    metrics = dict(summary.get("archive_validation") or {})
    if not metrics or metrics.get("retained_superseded_archives") not in {7, 8}:
        raise PublicationConflictError("validation summary archive metrics conflict")
    retained_finalized = [item for item in desired_report["superseded_archives"] if item.get("retained_finalized") is True]
    active_bytes = sum(int(item["archive_size"]) for item in desired_index["packages"])
    retained_bytes = sum(int(item["archive_size"]) for item in retained_finalized)
    desired_summary = copy.deepcopy(summary)
    desired_summary["archive_validation"].update({
        "bytes": active_bytes,
        "retained_superseded_archives": len(retained_finalized),
        "retained_superseded_bytes": retained_bytes,
        "stored_archives": len(desired_index["packages"]) + len(retained_finalized),
        "stored_bytes": active_bytes + retained_bytes,
    })
    desired_evidence = copy.deepcopy(evidence)
    evidence_matches = [item for item in desired_evidence.get("dnd", []) if item.get("id") == PACKAGE_ID]
    if len(evidence_matches) != 1 or evidence_matches[0].get("kind") != "addon":
        raise PublicationConflictError("public MCP evidence must contain exactly one Tortle addon")
    evidence_matches[0]["checksum"] = TARGET_CHECKSUM
    return desired_index, desired_report, desired_summary, desired_evidence


def _atomic_replace(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def publish(*, root: Path = ROOT, archive_builder: Callable[[bytes], bytes] | None = None, fail_after_replace: int | None = None) -> dict[str, Any]:
    root = root.resolve(); index_path, report_path, summary_path, evidence_path = (root / name for name in ("index.json", "migration-report.json", "validation-summary.json", "import-evidence.json"))
    if not root.is_dir() or not all(path.is_file() and path.resolve().parent == root for path in (index_path, report_path, summary_path, evidence_path)):
        raise PublicationConflictError("content-library metadata root is missing or unsafe")
    index, report, summary, evidence = (_read_object(path) for path in (index_path, report_path, summary_path, evidence_path))
    source_path = _safe_archive_path(root, SOURCE_PATH)
    if not source_path.is_file() or source_path.stat().st_size != SOURCE_ARCHIVE_SIZE or hashlib.sha256(source_path.read_bytes()).hexdigest() != SOURCE_ARCHIVE_SHA256:
        raise PublicationConflictError("reviewed Tortle 1.0.1 source archive conflicts")
    target_path_text = TARGET_PATH.format(checksum=TARGET_CHECKSUM[:12])
    target_path = _safe_archive_path(root, target_path_text)
    desired_index, desired_report, desired_summary, desired_evidence = _desired_metadata(index, report, summary, evidence, target_path_text)
    target_bytes = target_path.read_bytes() if target_path.exists() else (archive_builder or _build_target_archive)(source_path.read_bytes())
    if len(target_bytes) != TARGET_ARCHIVE_SIZE or hashlib.sha256(target_bytes).hexdigest() != TARGET_ARCHIVE_SHA256:
        raise PublicationConflictError("Tortle 1.0.2 target archive conflicts")
    old_bytes = {path: path.read_bytes() for path in (index_path, report_path, summary_path, evidence_path)}
    desired = [(target_path, target_bytes), (index_path, old_bytes[index_path] if index == desired_index else _object_bytes(desired_index, newline=_newline_for(old_bytes[index_path]))), (report_path, old_bytes[report_path] if report == desired_report else _object_bytes(desired_report, newline=_newline_for(old_bytes[report_path]))), (summary_path, old_bytes[summary_path] if summary == desired_summary else _object_bytes(desired_summary, newline=_newline_for(old_bytes[summary_path]))), (evidence_path, old_bytes[evidence_path] if evidence == desired_evidence else _object_bytes(desired_evidence, newline=_newline_for(old_bytes[evidence_path])))]
    writes = 0
    for path, content in desired:
        if path.exists() and path.read_bytes() == content:
            continue
        _atomic_replace(path, content); writes += 1
        if fail_after_replace == writes:
            raise InjectedPublicationFailure(f"injected failure after replacement {writes}")
    return {"id": PACKAGE_ID, "version": TARGET_VERSION, "checksum": TARGET_CHECKSUM, "status": "already_current" if writes == 0 else "published", "writes": writes, "path": target_path_text}


if __name__ == "__main__":
    print(json.dumps(publish()))
