"""Rebuild the authorized public D&D package catalog from canonical artifacts."""

from __future__ import annotations

import asyncio
import copy
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Mapping

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO.parent
for source_root in (
    WORKSPACE / "sagasmith-core" / "src",
    WORKSPACE / "sagasmith-dnd" / "src",
    WORKSPACE / "SagaSmith-dnd-mcp" / "src",
):
    sys.path.insert(0, str(source_root))

from sagasmith_core.portable import (  # noqa: E402
    build_actor_card,
    build_addon_pack,
    build_module_pack,
    build_preset_pack,
    build_rule_pack,
    dumps_module_archive,
    loads_module_archive,
)
from sagasmith_dnd.portable_cards import (  # noqa: E402
    build_srd2014_preset_pack,
    build_srd2024_preset_pack,
)
from sagasmith_dnd.public_library import (  # noqa: E402
    build_public_library,
    validate_public_package,
)
from sagasmith_dnd_mcp.config import McpConfig  # noqa: E402
from sagasmith_dnd_mcp.server import create_server  # noqa: E402

PUBLIC_LICENSE = "LicenseRef-SagaSmith-Authorized-Redistribution"
PUBLIC_ATTRIBUTION = (
    "Published by SagaSmithAI with redistribution authorization explicitly "
    "confirmed by the rights holder on 2026-08-08."
)
MODULE_SOURCE_PREFIXES = {
    "regression.d-d-5e-tomb-of-annihilation.": "tomb-of-annihilation",
    "regression.d-d-5e-tyranny-of-dragons-hoard-of-the-dragon-queen.": "hoard-of-the-dragon-queen",
    "regression.d-d-5e-tyranny-of-dragons-the-rise-of-tiamat.": "the-rise-of-tiamat",
    "regression.d-d-5e-waterdeep-dragon-heist.": "waterdeep-dragon-heist",
    "regression.lost-mine-of-phandelver.": "lost-mine-of-phandelver",
    "regression.storm-king-s-thunder-1-10.": "storm-kings-thunder",
    "regression.a-guide-to-storm-kings-thunder.": "a-guide-to-storm-kings-thunder",
}


def _public_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    original = copy.deepcopy(dict(value or {}))
    metadata = copy.deepcopy(original)
    metadata["distribution"] = "public"
    metadata["license"] = PUBLIC_LICENSE
    metadata["attribution"] = PUBLIC_ATTRIBUTION
    metadata["redistribution_authorization"] = {
        "confirmed": True,
        "confirmed_on": "2026-08-08",
        "scope": "public portable package redistribution",
        "original_distribution": original.get("distribution"),
        "original_license": original.get("license"),
        "original_attribution": original.get("attribution"),
    }
    return metadata


_COMPONENTS_BY_CHECKSUM: dict[str, Mapping[str, Any]] = {}
_REBUILT_COMPONENTS: dict[str, dict[str, Any]] = {}
_REBUILDING: set[str] = set()


def _dependencies(value: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    dependencies = []
    for raw in value:
        item = copy.deepcopy(dict(raw))
        checksum = item.get("checksum")
        source = _COMPONENTS_BY_CHECKSUM.get(str(checksum))
        if source is not None:
            item["checksum"] = _rebuild_component(source)["checksum"]
        dependencies.append(item)
    return dependencies


def _public_image(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    image = copy.deepcopy(dict(value))
    image["license"] = PUBLIC_LICENSE
    image["attribution"] = PUBLIC_ATTRIBUTION
    return image


def _rebuild_actor(package: Mapping[str, Any]) -> dict[str, Any]:
    payload = package["payload"]
    return build_actor_card(
        portable_id=package["id"],
        version=package["version"],
        system_id=package["system_id"],
        actor_type=payload["actor_type"],
        name=payload["name"],
        player_name=payload.get("player_name"),
        summary=payload.get("summary", ""),
        sheet=payload["sheet"],
        notes=payload["notes"],
        provenance=payload.get("provenance"),
        bindings=payload.get("bindings"),
        image=_public_image(payload.get("image")),
        metadata=_public_metadata(package.get("metadata")),
        dependencies=_dependencies(package.get("dependencies") or []),
    )


def _rebuild_component(package: Mapping[str, Any]) -> dict[str, Any]:
    source_checksum = str(package["checksum"])
    cached = _REBUILT_COMPONENTS.get(source_checksum)
    if cached is not None:
        return copy.deepcopy(cached)
    if source_checksum in _REBUILDING:
        raise RuntimeError(f"portable dependency cycle at {package['id']}")
    _REBUILDING.add(source_checksum)
    payload = package["payload"]
    common = {
        "portable_id": package["id"],
        "version": package["version"],
        "system_id": package["system_id"],
        "metadata": _public_metadata(package.get("metadata")),
        "dependencies": _dependencies(package.get("dependencies") or []),
    }
    if package["kind"] == "actor_card":
        rebuilt = _rebuild_actor(package)
    elif package["kind"] == "preset_pack":
        rebuilt = build_preset_pack(
            **common,
            cards=[_rebuild_actor(card) for card in payload["cards"]],
        )
    elif package["kind"] == "rule_pack":
        rebuilt = build_rule_pack(
            **common,
            manifest=payload["manifest"],
            artifacts=payload["artifacts"],
            mechanics=payload["mechanics"],
            provenance=payload.get("provenance"),
            sources=payload.get("sources"),
        )
    elif package["kind"] == "module_pack":
        rebuilt = build_module_pack(
            **common,
            manifest=payload["manifest"],
            source=payload["source"],
            document=payload["document"],
            scene_atlas=payload["scene_atlas"],
            assets=payload.get("assets"),
            content_reviews=payload.get("content_reviews"),
            actors=[_rebuild_actor(card) for card in payload.get("actors") or []],
            catalogs=payload["catalogs"],
            narrative=payload["narrative"],
            readiness=payload["readiness"],
        )
    else:
        raise ValueError(f"unsupported nested package kind: {package['kind']}")
    _REBUILDING.remove(source_checksum)
    _REBUILT_COMPONENTS[source_checksum] = rebuilt
    return copy.deepcopy(rebuilt)


def _rebuild_addon(package: Mapping[str, Any]) -> dict[str, Any]:
    payload = package["payload"]
    metadata = _public_metadata(package.get("metadata"))
    # Core models addon releases as private/shareable; shareable is the public
    # library state and is accepted by the library license gate.
    metadata["distribution"] = "shareable"
    return build_addon_pack(
        portable_id=package["id"],
        version=package["version"],
        system_id=package["system_id"],
        manifest=payload["manifest"],
        components=[_rebuild_component(item) for item in payload["components"]],
        metadata=metadata,
    )


def _select_addons() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: dict[str, tuple[Path, dict[str, Any]]] = {}
    root = WORKSPACE / "SagaSmith-dnd-mcp" / "tmp"
    for path in root.rglob("*.addon.sagasmith.json"):
        package = json.loads(path.read_text(encoding="utf-8"))
        package_id = str(package["id"])
        if package_id.endswith(".namefix") or package_id.startswith(
            "dnd5e.regression.rulebook."
        ):
            continue
        current = candidates.get(package_id)
        if current is None or path.stat().st_mtime_ns > current[0].stat().st_mtime_ns:
            candidates[package_id] = (path, package)
    for _, package in candidates.values():
        for component in package["payload"]["components"]:
            _COMPONENTS_BY_CHECKSUM[str(component["checksum"])] = component
    packages = []
    audit = []
    for package_id, (path, package) in sorted(candidates.items()):
        rebuilt = _rebuild_addon(package)
        validate_public_package(rebuilt)
        packages.append(rebuilt)
        audit.append(
            {
                "kind": "addon_pack",
                "id": package_id,
                "selected_source": str(path.relative_to(WORKSPACE)).replace("\\", "/"),
                "source_checksum": package["checksum"],
                "published_checksum": rebuilt["checksum"],
            }
        )
    return packages, audit


def _unwrap_tool_result(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and value and hasattr(value[0], "text"):
        return json.loads(value[0].text)
    if hasattr(value, "structured_content") and value.structured_content is not None:
        return value.structured_content
    raise TypeError(f"cannot unwrap MCP result of type {type(value)!r}")


async def _call(server: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    raw = await server.call_tool(name, arguments)
    result = raw[1] if isinstance(raw, tuple) and len(raw) == 2 else raw
    value = _unwrap_tool_result(result)
    return value.get("result", value)


def _parser_rank(campaign: Mapping[str, Any], module: Mapping[str, Any]) -> tuple[int, int, int]:
    raw = str(module.get("parser_version") or "0")
    match = re.search(r"\d+", raw)
    return (
        int(match.group()) if match else 0,
        int("[469195a0]" in str(campaign.get("name") or "")),
        int(campaign.get("revision") or 0),
    )


def _module_manifest(slug: str, title: str) -> dict[str, Any]:
    series_id = None
    order = None
    continues_from = None
    classification = "campaign"
    state_policy: dict[str, Any] = {}
    if slug in {"hoard-of-the-dragon-queen", "the-rise-of-tiamat"}:
        series_id = "dnd5e.series.tyranny-of-dragons"
        order = 1 if slug == "hoard-of-the-dragon-queen" else 2
        if order == 2:
            continues_from = "dnd5e.module.hoard-of-the-dragon-queen"
            state_policy = {
                "inherit": [
                    "party",
                    "levels",
                    "experience",
                    "inventory",
                    "relationships",
                    "quests",
                    "world_state",
                    "actor_knowledge",
                ],
                "exclude": ["scene_progress", "temporary_effects"],
            }
    if slug == "a-guide-to-storm-kings-thunder":
        classification = "dm_guide"
        continues_from = "dnd5e.module.storm-kings-thunder"
    return {
        "title": title,
        "classification": classification,
        "compatibility": {
            "editions": ["2014"],
            "required_capabilities": ["module_pack_v2", "agent_narrative_ruling"],
        },
        "play_profile": {
            "party_size": {"minimum": None, "maximum": None, "source_refs": []},
            "starting_level": {"value": None, "source_refs": []},
            "expected_end_level": {"value": None, "source_refs": []},
            "advancement": {
                "modes": ["unknown"],
                "recommended": "unknown",
                "source_refs": [],
            },
            "pregenerated_characters": {
                "available": False,
                "applicability": "Awaiting source-backed review",
                "source_refs": [],
            },
        },
        "continuity": {
            "series_id": series_id,
            "order": order,
            "continues_from": continues_from,
            "state_policy": state_policy,
        },
        "activation": {"mode": "campaign_attach", "default_active": False},
        "content_summary": {},
    }


async def _export_modules() -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], dict[str, bytes]
]:
    base = McpConfig.from_environment()
    home = WORKSPACE / ".regression-cache" / "campaign-corpus-home-v3"
    config = McpConfig(
        home=home.resolve(),
        database_url=None,
        chroma_url=None,
        chroma_path_override=None,
        dnd_skills_dir=base.dnd_skills_dir,
        modulegen_skills_dir=base.modulegen_skills_dir,
        auto_seed_rules=False,
        rule_import_roots=(),
        module_import_roots=(),
    )
    server = create_server(config)
    campaigns = await _call(server, "campaign_query", {"view": "list"})
    selected: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for campaign in campaigns:
        imported = await _call(
            server,
            "module_query",
            {"campaign_id": campaign["id"], "view": "list"},
        )
        for active in imported:
            logical_key = str(active.get("logical_source_key") or "")
            slug = next(
                (
                    value
                    for prefix, value in MODULE_SOURCE_PREFIXES.items()
                    if logical_key.startswith(prefix)
                ),
                None,
            )
            if slug is None:
                continue
            current = selected.get(slug)
            if current is None or _parser_rank(campaign, active) > _parser_rank(*current):
                selected[slug] = (campaign, active)
    missing = set(MODULE_SOURCE_PREFIXES.values()) - set(selected)
    if missing:
        raise RuntimeError(f"missing canonical module sources: {sorted(missing)}")
    packages = []
    audit = []
    archives: dict[str, bytes] = {}
    published_by_slug: dict[str, dict[str, Any]] = {}
    order = [
        "hoard-of-the-dragon-queen",
        "lost-mine-of-phandelver",
        "storm-kings-thunder",
        "tomb-of-annihilation",
        "waterdeep-dragon-heist",
        "the-rise-of-tiamat",
        "a-guide-to-storm-kings-thunder",
    ]
    for slug in order:
        campaign, active = selected[slug]
        source_key = str(active["logical_source_key"])
        portable_id = "dnd5e.module." + slug
        dependencies = []
        dependency_slug = {
            "the-rise-of-tiamat": "hoard-of-the-dragon-queen",
            "a-guide-to-storm-kings-thunder": "storm-kings-thunder",
        }.get(slug)
        if dependency_slug is not None:
            dependency = published_by_slug[dependency_slug]
            dependencies.append(
                {
                    "kind": "module_pack",
                    "id": dependency["id"],
                    "version": dependency["version"],
                    "checksum": dependency["checksum"],
                    "optional": False,
                }
            )
        metadata = _public_metadata(
            {
                "title": active.get("title") or source_key,
                "source_key": source_key,
                "parser_version": active.get("parser_version"),
            }
        )
        exported = await _call(
            server,
            "module_query",
            {
                "campaign_id": campaign["id"],
                "view": "package",
                "payload": {
                    "module_id": active["id"],
                    "portable_id": portable_id,
                    "version": "1.0.0",
                    "metadata": metadata,
                    "dependencies": dependencies,
                    "manifest": _module_manifest(
                        slug, str(active.get("title") or source_key)
                    ),
                    "include_package": True,
                },
            },
        )
        archive_path = config.portable_packages_dir / exported["artifact"]
        _exported_package, blobs = loads_module_archive(archive_path.read_bytes())
        rebuilt = _rebuild_component(exported["package"])
        validate_public_package(rebuilt)
        archive = dumps_module_archive(rebuilt, blobs)
        packages.append(rebuilt)
        published_by_slug[slug] = rebuilt
        archives[rebuilt["checksum"]] = archive
        audit.append(
            {
                "kind": "module_pack",
                "id": rebuilt["id"],
                "campaign_id": campaign["id"],
                "module_id": active["id"],
                "source_key": source_key,
                "parser_version": active.get("parser_version"),
                "published_checksum": rebuilt["checksum"],
            }
        )
    return packages, audit, archives


def main() -> None:
    skill_root = WORKSPACE / "SagaSmith-dnd-skills"
    output = REPO / "public" / "content-library"
    addons, addon_audit = _select_addons()
    modules, module_audit, module_archives = asyncio.run(_export_modules())
    presets = [
        _rebuild_component(build_srd2014_preset_pack(skill_root)),
        _rebuild_component(build_srd2024_preset_pack(skill_root)),
    ]
    packages = [*presets, *addons, *modules]
    package_dir = output / "packages"
    if package_dir.exists():
        for stale_package in package_dir.iterdir():
            if not stale_package.is_file():
                continue
            stale_package.unlink()
    index = build_public_library(
        output, packages, module_archives=module_archives
    )
    audit = {
        "schema": "sagasmith.public-content-library-audit.v1",
        "generated_on": date.today().isoformat(),
        "authorization": {
            "license": PUBLIC_LICENSE,
            "confirmed_on": "2026-08-08",
            "scope": "public portable package redistribution",
        },
        "counts": {
            "preset_pack": len(presets),
            "addon_pack": len(addons),
            "module_pack": len(modules),
            "total": len(packages),
        },
        "sources": [*addon_audit, *module_audit],
        "published": [
            {key: item[key] for key in ("kind", "id", "version", "checksum")}
            for item in packages
        ],
    }
    (output / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"counts": audit["counts"], "index_entries": len(index["packages"])}, indent=2))


if __name__ == "__main__":
    main()
