"""Rebuild the complete private catalog from current unified corpus outputs.

Rulebook addons are compiled by the MCP regression driver.  Existing module
and preset packages are semantic inputs, not legacy transport formats: this
script revalidates and re-signs them with the current content-package builder,
updates dependency locks, embeds original documents, and re-extracts every
source-backed actor portrait.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO.parent
for source_root in (
    WORKSPACE / "sagasmith-core" / "src",
    WORKSPACE / "sagasmith-dnd" / "src",
):
    sys.path.insert(0, str(source_root))

from sagasmith_core.content_pack import (
    build_content_package,
    dumps_content_archive,
    loads_content_archive,
)
from sagasmith_dnd.content_packages import (
    attach_actor_portraits,
    attach_auxiliary_assets,
    attach_source_originals,
    build_preset_content_package,
    canonicalize_dnd_content_package,
)
from sagasmith_dnd.portable_cards import (
    build_srd2014_preset_pack,
    build_srd2024_preset_pack,
)
from sagasmith_dnd.public_library import build_content_library

VERSION = "2.0.0"
PRIVATE_LICENSE = "user-supplied"
PRIVATE_ATTRIBUTION = "User supplied source; redistribution rights not asserted."
CORE_PACKAGE_IDS = {
    "d&d 5e - dungeon master's guide": "dnd5e.core-rules.dmg2014",
    "d&d 5e - monster manual": "dnd5e.core-rules.mm2014",
    "d&d 5e - player's handbook": "dnd5e.core-rules.phb2014",
}
MODULE_PDFS = {
    "dnd5e.module.hoard-of-the-dragon-queen": (
        "D&D 5E - Tyranny of Dragons - Hoard of the Dragon Queen.pdf"
    ),
    "dnd5e.module.lost-mine-of-phandelver": (
        "Lost Mine of Phandelver/Lost Mine of Phandelver.pdf"
    ),
    "dnd5e.module.storm-kings-thunder": (
        "Storm King's Thunder/Storm King's Thunder (1-10).pdf"
    ),
    "dnd5e.module.the-rise-of-tiamat": (
        "D&D 5E - Tyranny of Dragons - The Rise of Tiamat.pdf"
    ),
    "dnd5e.module.tomb-of-annihilation": "D&D 5E - Tomb of Annihilation.pdf",
    "dnd5e.module.waterdeep-dragon-heist": (
        "D&D 5E - Waterdeep - Dragon Heist.pdf"
    ),
    "dnd5e.module.a-guide-to-storm-kings-thunder": (
        "Storm King's Thunder/A_Guide_to_Storm_Kings_Thunder.pdf"
    ),
}
MODULE_AUXILIARY = {
    "dnd5e.module.lost-mine-of-phandelver": [
        ("Lost Mine of Phandelver/PC-Smalls.pdf", "player_reference"),
        ("Lost Mine of Phandelver/Sword Coast Map.png", "map"),
    ],
    "dnd5e.module.storm-kings-thunder": [
        ("Storm King's Thunder/DrippingCaves.png", "map"),
        ("Storm King's Thunder/Nightstone.png", "map"),
        ("Storm King's Thunder/SKT-PCStats.txt", "player_reference"),
        *[
            (f"Storm King's Thunder/Characters/{name}.pdf", "player_reference")
            for name in (
                "AncestralGuardianBarbarian",
                "HunterRanger",
                "OpenHandMonk",
                "ShadowSorcerer",
                "TempestCleric",
                "VengencePaladin",
                "WildSorcerer",
            )
        ],
    ],
}
PRESET_EVIDENCE_ALIASES = {
    "animated-flying-sword": "flying-sword",
    "animated-rug-of-smothering": "rug-of-smothering",
    "cultist-fanatic": "cult-fanatic",
    "elf-drow": "drow",
    "giant-seahorse": "giant-sea-horse",
    "giant-venomous-snake": "giant-poisonous-snake",
    "gnome-deep-svirfneblin": "deep-gnome-svirfneblin",
    "half-dragon": "source-fragment-half-dragon-template-p-181",
    "half-dragon-template": "source-fragment-half-dragon-template-p-181",
    "incubus": "succubus-incubus",
    "piranha": "quipper",
    "seahorse": "sea-horse",
    "shrieker-fungus": "shrieker",
    "succubus": "succubus-incubus",
    "swarm-of-piranhas": "swarm-of-quippers",
    "swarm-of-venomous-snakes": "swarm-of-poisonous-snakes",
    "venomous-snake": "poisonous-snake",
}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _load_archives(
    directory: Path,
    *,
    kinds: set[str] | None = None,
) -> dict[str, tuple[dict, dict[str, bytes]]]:
    result = {}
    for path in sorted(directory.glob("*.sagasmith-pack")):
        package, blobs = loads_content_archive(path.read_bytes())
        if kinds is not None and str(package["kind"]) not in kinds:
            continue
        package_id = str(package["id"])
        if package_id in result:
            raise ValueError(f"duplicate package id in {directory}: {package_id}")
        result[package_id] = (package, blobs)
    return result


def _rebuild(package: dict, **changes: object) -> dict:
    values = {
        "kind": package["kind"],
        "package_id": package["id"],
        "version": package["version"],
        "system_id": package["system_id"],
        "manifest": package["manifest"],
        "dependencies": package["dependencies"],
        "sources": package["sources"],
        "assets": package["assets"],
        "content_reviews": package["content_reviews"],
        "actors": package["actors"],
        "content": package["content"],
        "metadata": package["metadata"],
    }
    values.update(changes)
    return build_content_package(**values)


def _publish(package: dict, *, kind: str | None = None, package_id: str | None = None) -> dict:
    target_id = package_id or str(package["id"])
    target_kind = kind or str(package["kind"])
    manifest = copy.deepcopy(dict(package["manifest"]))
    manifest.update(
        {"id": target_id, "version": VERSION, "system_id": package["system_id"]}
    )
    actors = copy.deepcopy(list(package["actors"]))
    for actor in actors:
        actor["version"] = VERSION
    metadata = copy.deepcopy(dict(package["metadata"]))
    metadata.update(
        {
            "distribution": "private",
            "license": PRIVATE_LICENSE,
            "attribution": PRIVATE_ATTRIBUTION,
        }
    )
    metadata.pop("redistribution_authorization", None)
    assets = copy.deepcopy(list(package["assets"]))
    for asset in assets:
        asset["license"] = PRIVATE_LICENSE
        asset["attribution"] = PRIVATE_ATTRIBUTION
    return _rebuild(
        package,
        kind=target_kind,
        package_id=target_id,
        version=VERSION,
        manifest=manifest,
        assets=assets,
        actors=actors,
        metadata=metadata,
    )


def _without_actor_images(
    package: dict, blobs: dict[str, bytes]
) -> tuple[dict, dict[str, bytes]]:
    actors = copy.deepcopy(list(package["actors"]))
    for actor in actors:
        actor["image"] = None
    content = copy.deepcopy(dict(package["content"]))
    for artifact in content.get("artifacts") or []:
        if not isinstance(artifact, dict) or artifact.get("kind") != "statblock":
            continue
        card = artifact.get("card")
        if isinstance(card, dict):
            card.pop("image", None)
    removed = {
        str(asset["checksum"])
        for asset in package["assets"]
        if asset["kind"] == "actor_image"
    }
    assets = [
        copy.deepcopy(asset)
        for asset in package["assets"]
        if asset["kind"] != "actor_image"
    ]
    retained = {str(asset["checksum"]) for asset in assets}
    next_blobs = {
        key: value
        for key, value in blobs.items()
        if key not in removed or key in retained
    }
    return _rebuild(package, assets=assets, actors=actors, content=content), next_blobs


def _without_original_documents(
    package: dict, blobs: dict[str, bytes]
) -> tuple[dict, dict[str, bytes]]:
    sources = copy.deepcopy(list(package["sources"]))
    original_keys = {
        str(asset_key)
        for source in sources
        for asset_key in source["original_asset_keys"]
    }
    for source in sources:
        source["original_asset_keys"] = []
    removed = {
        str(asset["checksum"])
        for asset in package["assets"]
        if str(asset["asset_key"]) in original_keys
    }
    assets = [
        copy.deepcopy(asset)
        for asset in package["assets"]
        if str(asset["asset_key"]) not in original_keys
    ]
    retained = {str(asset["checksum"]) for asset in assets}
    next_blobs = {
        key: value
        for key, value in blobs.items()
        if key not in removed or key in retained
    }
    return _rebuild(package, sources=sources, assets=assets), next_blobs


def _book_source_paths(package: dict, books: list[Path]) -> dict[str, Path]:
    by_title = {_slug(path.stem): path for path in books}
    result = {}
    for source in package["sources"]:
        title = _slug(str(source["title"]))
        exact = by_title.get(title)
        if exact is not None:
            result[str(source["source_key"])] = exact
            continue
        ranked = sorted(
            (
                (len(set(title.split("-")) & set(candidate.split("-"))), path)
                for candidate, path in by_title.items()
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        if ranked and ranked[0][0] >= max(2, len(set(title.split("-"))) // 2):
            result[str(source["source_key"])] = ranked[0][1]
    return result


def _module_source_paths(package: dict, campaign_root: Path) -> dict[str, Path]:
    relative = MODULE_PDFS.get(str(package["id"]))
    if relative is None:
        return {}
    path = campaign_root / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    primary = next(
        (
            source
            for source in package["sources"]
            if str(source.get("authority") or "") == "module"
        ),
        package["sources"][0],
    )
    return {str(primary["source_key"]): path}


def _module_auxiliary_entries(package: dict, campaign_root: Path) -> list[dict]:
    entries = []
    for relative, kind in MODULE_AUXILIARY.get(str(package["id"]), []):
        path = campaign_root / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        entries.append(
            {
                "path": path,
                "kind": kind,
                "logical_path": relative.replace("\\", "/"),
                "metadata": {"module_id": package["id"]},
            }
        )
    return entries


def _with_portraits(
    package: dict,
    blobs: dict[str, bytes],
    source_paths: dict[str, Path],
    portrait_library: dict,
    portrait_reviews: dict[str, dict],
) -> tuple[dict, dict[str, bytes], dict, dict]:
    package, blobs = _without_actor_images(package, blobs)
    package, blobs, audit, portrait_library = attach_actor_portraits(
        package,
        blobs,
        source_paths,
        portrait_library=portrait_library,
        portrait_reviews={
            key: value
            for key, value in portrait_reviews.items()
            if key.startswith(f"{package['id']}|")
        },
        minimum_confidence=0.40,
    )
    return package, blobs, audit, portrait_library


def _load_portrait_reviews(path: Path | None) -> tuple[dict[str, dict], dict | None]:
    if path is None:
        return {}, None
    resolved = path.expanduser().resolve()
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"schema", "reviews"}:
        raise ValueError("portrait review file must contain exact schema and reviews fields")
    if payload["schema"] != "sagasmith.portrait-reviews.v1":
        raise ValueError("unsupported portrait review schema")
    raw_reviews = payload["reviews"]
    if not isinstance(raw_reviews, dict) or any(
        not isinstance(key, str) or not isinstance(value, dict)
        for key, value in raw_reviews.items()
    ):
        raise ValueError("portrait reviews must map exact subject keys to objects")
    return (
        {str(key): dict(value) for key, value in raw_reviews.items()},
        {
            "path": str(resolved),
            "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
            "review_count": len(raw_reviews),
        },
    )


def _write_portrait_review_queue(
    path: Path | None,
    image_audits: dict[str, dict],
) -> None:
    """Persist a deterministic, private review queue before failing closed."""

    if path is None:
        return
    reviews = {
        str(item["review_key"]): {
            "package_id": package_id,
            "subject_type": item["subject_type"],
            "subject_id": item["subject_id"],
            "name": item["name"],
            "sources": list(item.get("sources") or []),
            "diagnostics": list(item.get("diagnostics") or []),
            "reason": str(item.get("reason") or ""),
        }
        for package_id, audit in sorted(image_audits.items())
        for item in audit.get("review_required") or []
    }
    payload = {
        "schema": "sagasmith.portrait-review-queue.v1",
        "reviews": reviews,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _require_reviewed_portrait_audits(image_audits: dict[str, dict]) -> None:
    """Reject a release when extraction uncertainty has not been resolved.

    A source page genuinely lacking a usable illustration is a valid final
    state.  A missing heading, invalid page, low-confidence crop, or undersized
    candidate is not: those cases require a corrected source reference or a
    human/agent-approved image before the package can be published.
    """

    unresolved = {
        package_id: list(audit.get("review_required") or [])
        for package_id, audit in image_audits.items()
        if audit.get("review_required")
    }
    if unresolved:
        summary = "; ".join(
            f"{package_id}: "
            + ", ".join(
                f"{item.get('name', item.get('actor_id', 'unknown'))}"
                for item in items
            )
            for package_id, items in sorted(unresolved.items())
        )
        raise ValueError(f"unresolved actor portrait extraction reviews: {summary}")


def _preset_with_rulebook_evidence(
    package: dict,
    blobs: dict[str, bytes],
    evidence_package: dict,
    evidence_blobs: dict[str, bytes],
) -> tuple[dict, dict[str, bytes], int]:
    """Attach exact rulebook evidence to matching preset actors before art extraction."""

    actor_evidence_by_name: dict[str, list[list[dict]]] = {}
    artifact_evidence_by_name: dict[str, list[list[dict]]] = {}
    for actor in evidence_package["actors"]:
        refs = list(dict(actor.get("provenance") or {}).get("source_refs") or [])
        if any(isinstance(ref.get("page"), int) for ref in refs):
            actor_evidence_by_name.setdefault(_slug(str(actor["name"])), []).append(refs)
    for artifact in evidence_package["content"].get("artifacts") or []:
        refs = list(artifact.get("source_refs") or [])
        name = _slug(str(dict(artifact.get("card") or {}).get("name") or ""))
        if name and any(isinstance(ref.get("page"), int) for ref in refs):
            artifact_evidence_by_name.setdefault(name, []).append(refs)

    actors = copy.deepcopy(list(package["actors"]))
    matched = 0
    for actor in actors:
        names = [_slug(str(actor["name"]))]
        without_qualifier = _slug(re.sub(r"\s*\([^)]*\)\s*$", "", str(actor["name"])))
        if without_qualifier and without_qualifier not in names:
            names.append(without_qualifier)
        alias = PRESET_EVIDENCE_ALIASES.get(names[0])
        if alias:
            names.insert(0, alias)
        candidates: list[list[dict]] = []
        for name in names:
            candidates = actor_evidence_by_name.get(name, [])
            if not candidates:
                candidates = artifact_evidence_by_name.get(name, [])
            if candidates:
                break
        page_sets = {
            tuple(
                sorted(
                    {
                        (str(ref["source_key"]), int(ref["page"]))
                        for ref in refs
                        if isinstance(ref.get("page"), int)
                    }
                )
            )
            for refs in candidates
        }
        if len(page_sets) != 1:
            continue
        evidence_refs = list(
            {
                (
                    str(ref["source_key"]),
                    str(ref["chunk_key"]),
                    ref.get("page"),
                    str(ref.get("note") or ""),
                ): ref
                for refs in candidates
                for ref in refs
            }.values()
        )
        provenance = copy.deepcopy(dict(actor.get("provenance") or {}))
        refs = [*list(provenance.get("source_refs") or []), *evidence_refs]
        provenance["source_refs"] = list(
            {
                (
                    str(ref["source_key"]),
                    str(ref["chunk_key"]),
                    ref.get("page"),
                    str(ref.get("note") or ""),
                ): copy.deepcopy(ref)
                for ref in refs
            }.values()
        )
        actor["provenance"] = provenance
        matched += 1

    sources = [
        *copy.deepcopy(list(package["sources"])),
        *copy.deepcopy(list(evidence_package["sources"])),
    ]
    evidence_asset_keys = {
        str(source["normalized_document_asset_key"])
        for source in evidence_package["sources"]
    } | {
        str(asset_key)
        for source in evidence_package["sources"]
        for asset_key in source["original_asset_keys"]
    }
    evidence_assets = [
        copy.deepcopy(asset)
        for asset in evidence_package["assets"]
        if str(asset["asset_key"]) in evidence_asset_keys
    ]
    assets = [*copy.deepcopy(list(package["assets"])), *evidence_assets]
    next_blobs = dict(blobs)
    for asset in evidence_assets:
        checksum = str(asset["checksum"])
        next_blobs[checksum] = evidence_blobs[checksum]
    return (
        _rebuild(
            package,
            sources=sources,
            assets=assets,
            actors=actors,
        ),
        next_blobs,
        matched,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rulebook-pack-dir", type=Path, required=True)
    parser.add_argument(
        "--semantic-input-dir",
        type=Path,
        default=WORKSPACE / "tmp" / "unified-content-build-cache",
        help="current unified module archives used as semantic inputs",
    )
    parser.add_argument(
        "--books",
        type=Path,
        default=WORKSPACE / "reference" / "DnD-Books" / "5e" / "Books",
    )
    parser.add_argument(
        "--campaigns",
        type=Path,
        default=WORKSPACE / "reference" / "DnD-Books" / "5e" / "Campaign",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=WORKSPACE / "tmp" / "unified-private-content-library",
    )
    parser.add_argument(
        "--portrait-review-file",
        type=Path,
        help=(
            "private Agent/human decisions for uncertain portrait crops; the file is "
            "audited but is not copied into the public catalog"
        ),
    )
    parser.add_argument(
        "--portrait-review-output",
        type=Path,
        help=(
            "write a deterministic private queue for unresolved portrait decisions "
            "before the release gate fails"
        ),
    )
    args = parser.parse_args()
    portrait_reviews, portrait_review_manifest = _load_portrait_reviews(
        args.portrait_review_file
    )

    # Semantic inputs are current, already Agent-finalized module packages.
    # Legacy descriptors and editable drafts are intentionally rejected here.
    current = _load_archives(
        args.semantic_input_dir,
        kinds={"module"},
    )
    generated = {
        package_id: (canonicalize_dnd_content_package(package), blobs)
        for package_id, (package, blobs) in _load_archives(
            args.rulebook_pack_dir
        ).items()
    }
    if len(generated) != 21:
        raise ValueError(f"expected 21 current rulebook packages, found {len(generated)}")
    retained: dict[str, tuple[dict, dict[str, bytes]]] = {
        package_id: value
        for package_id, value in current.items()
        if value[0]["kind"] == "module"
    }
    if sum(value[0]["kind"] == "module" for value in retained.values()) != 7:
        raise ValueError(
            "catalog must retain seven Agent-finalized source adventure modules"
        )
    skill_root = WORKSPACE / "SagaSmith-dnd-skills"
    for portable in (
        build_srd2014_preset_pack(skill_root),
        build_srd2024_preset_pack(skill_root),
    ):
        if not portable:
            raise ValueError("bundled SRD actor presets are unavailable")
        preset, preset_blobs = build_preset_content_package(
            package_id=str(portable["id"]),
            version=VERSION,
            system_id=str(portable["system_id"]),
            title=str(dict(portable["metadata"])["title"]),
            cards=list(portable["payload"]["cards"]),
            metadata=dict(portable["metadata"]),
        )
        retained[str(preset["id"])] = (preset, preset_blobs)

    books = sorted(args.books.rglob("*.pdf"))
    rulebook_id_map = {
        str(package["id"]): CORE_PACKAGE_IDS.get(
            str(package["manifest"]["title"]).casefold(),
            str(package["id"]),
        )
        for package, _blobs in generated.values()
    }
    packages: dict[str, tuple[dict, dict[str, bytes]]] = {}
    image_audits: dict[str, dict] = {}
    portrait_library: dict = {}
    for raw_package, raw_blobs in generated.values():
        title = str(raw_package["manifest"]["title"]).casefold()
        is_core = title in CORE_PACKAGE_IDS
        package_id = CORE_PACKAGE_IDS.get(title)
        package = _publish(
            raw_package,
            kind="core_rules" if is_core else "addon",
            package_id=package_id,
        )
        package = _rebuild(
            package,
            dependencies=[
                {
                    **dependency,
                    "id": rulebook_id_map.get(
                        str(dependency["id"]), str(dependency["id"])
                    ),
                }
                for dependency in package["dependencies"]
            ],
        )
        blobs = dict(raw_blobs)
        source_paths = _book_source_paths(package, books)
        primary_sources = [
            source
            for source in package["sources"]
            if str(source.get("authority") or "") != "preset"
        ]
        if not primary_sources or any(
            str(source["source_key"]) not in source_paths for source in primary_sources
        ):
            raise ValueError(f"original rulebook PDF was not matched for {package['id']}")
        package, blobs = attach_source_originals(package, blobs, source_paths)
        package, blobs, image_audit, portrait_library = _with_portraits(
            package,
            blobs,
            source_paths,
            portrait_library,
            portrait_reviews,
        )
        packages[str(package["id"])] = (package, blobs)
        image_audits[str(package["id"])] = image_audit
        print(
            f"rulebook {package['id']}: {image_audit['images']}/"
            f"{image_audit['actors']} portraits",
            flush=True,
        )

    for package_id, (raw_package, raw_blobs) in retained.items():
        package = _publish(raw_package)
        blobs = dict(raw_blobs)
        if package["kind"] == "module":
            source_paths = _module_source_paths(package, args.campaigns)
            package, blobs = _without_original_documents(package, blobs)
            package, blobs = attach_source_originals(package, blobs, source_paths)
            package, blobs = attach_auxiliary_assets(
                package,
                blobs,
                _module_auxiliary_entries(package, args.campaigns),
            )
            package, blobs, image_audit, portrait_library = _with_portraits(
                package,
                blobs,
                source_paths,
                portrait_library,
                portrait_reviews,
            )
        else:
            evidence_package, evidence_blobs = packages["dnd5e.core-rules.mm2014"]
            package, blobs = _without_actor_images(package, blobs)
            package, blobs, matched = _preset_with_rulebook_evidence(
                package,
                blobs,
                evidence_package,
                evidence_blobs,
            )
            source_paths = _book_source_paths(evidence_package, books)
            package, blobs, image_audit, portrait_library = _with_portraits(
                package,
                blobs,
                source_paths,
                portrait_library,
                portrait_reviews,
            )
            image_audit["evidence_matched"] = matched
            image_audit["evidence_source_package"] = evidence_package["id"]
        packages[package_id] = (package, blobs)
        image_audits[package_id] = image_audit
        print(
            f"{package['kind']} {package_id}: {image_audit['images']}/"
            f"{image_audit['actors']} portraits",
            flush=True,
        )

    applied_portrait_reviews = {
        str(review["review_key"])
        for audit in image_audits.values()
        for review in audit.get("reviewed") or []
    }
    unmatched_portrait_reviews = sorted(set(portrait_reviews) - applied_portrait_reviews)
    if unmatched_portrait_reviews:
        raise ValueError(
            "portrait review file contains stale or unmatched subjects: "
            + ", ".join(unmatched_portrait_reviews)
        )
    _write_portrait_review_queue(args.portrait_review_output, image_audits)
    _require_reviewed_portrait_audits(image_audits)

    remaining = dict(packages)
    rebuilt: dict[str, dict] = {}
    ordered = []
    archives = {}
    while remaining:
        progressed = False
        for package_id, (package, blobs) in list(remaining.items()):
            required = [
                str(item["id"])
                for item in package["dependencies"]
                if not item["optional"]
            ]
            if any(item in remaining for item in required):
                continue
            dependencies = [
                {
                    **item,
                    **(
                        {
                            "version": rebuilt[str(item["id"])]["version"],
                            "checksum": rebuilt[str(item["id"])]["checksum"],
                        }
                        if str(item["id"]) in rebuilt
                        else {}
                    ),
                }
                for item in package["dependencies"]
            ]
            package = _rebuild(package, dependencies=dependencies)
            archive = dumps_content_archive(package, blobs)
            rebuilt[package_id] = package
            ordered.append(package)
            archives[str(package["checksum"])] = archive
            del remaining[package_id]
            progressed = True
        if not progressed:
            raise ValueError(f"content package dependency cycle: {sorted(remaining)}")

    index = build_content_library(args.output, ordered, archives=archives)
    audit_path = args.output / "audit.json"
    counts = Counter(str(item["kind"]) for item in index["packages"])
    audit = {
        "schema": "sagasmith.content-library-audit.v1",
        "visibility": "private",
        "package_version": VERSION,
        "counts": dict(sorted(counts.items())),
        "total": len(index["packages"]),
        "images": sum(item["image_count"] for item in index["packages"]),
        "content_card_images": sum(
            image_audit["statblock_card_images"] for image_audit in image_audits.values()
        ),
        "packages": [
            {
                "kind": item["kind"],
                "id": item["id"],
                "version": item["version"],
                "checksum": item["checksum"],
                "actors": item["component_counts"]["actor_card"],
                "images": item["image_count"],
                "validated": True,
            }
            for item in index["packages"]
        ],
        "image_extraction": image_audits,
        "portrait_review_manifest": portrait_review_manifest,
    }
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"packages": len(ordered), "images": audit["images"]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
