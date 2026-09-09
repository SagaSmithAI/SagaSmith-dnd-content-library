"""Refresh public MCP import evidence for replaced D&D Packs."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

import sagasmith_dnd
from sagasmith_core.content_pack import loads_content_archive
from sagasmith_dnd_mcp.config import McpConfig
from sagasmith_dnd_mcp.server import create_server

ROOT = Path(__file__).resolve().parents[1] / "content-library"
TARGET_IDS = frozenset(
    {
        "dnd5e.addon.rulebook.d-d-5e-eberron-rising-from-the-last-war.31293633134f.addon",
        "dnd5e.addon.rulebook.d-d-5e-guildmasters-guide-to-ravnica.59317c5cf3da.addon",
        "dnd5e.addon.rulebook.d-d-5e-mordenkainen-s-tome-of-foes.2768304ef1af.addon",
        "dnd5e.addon.rulebook.d-d-5e-player-s-handbook.7ad6d3e9c93c.addon",
        "dnd5e.addon.rulebook.d-d-5e-sword-coast-adventurer-s-guide.16e6a243ef0a.addon",
        "dnd5e.addon.rulebook.d-d-5e-tasha-s-cauldron-of-everything.89a729b37a4b.addon",
        "dnd5e.addon.rulebook.d-d-5e-wayfinders-guide-to-eberron.38e71ffb60c7.addon",
        "dnd5e.addon.rulebook.d-d-5e-volo-s-guide-to-monsters.962933255634.addon",
        "906e1c57-005d-4bf1-8b03-221e0726e27d",
        "d0871484-131a-418f-aba3-016e944411ab",
        "dnd5e.module.lost-mine-of-phandelver.full-agent-corpus-v12",
        "dnd5e.module.waterdeep-dragon-heist",
    }
)


async def _call(server, name: str, arguments: dict[str, Any]) -> Any:
    _content, response = await server.call_tool(name, arguments)
    if isinstance(response, dict):
        return response.get("result", response)
    return response


async def _refresh(
    index: dict[str, Any], target_ids: frozenset[str]
) -> dict[str, dict[str, Any]]:
    packages = {
        str(item.get("id") or ""): item
        for item in index.get("packages") or []
        if isinstance(item, dict)
    }
    if not target_ids.issubset(packages):
        raise ValueError("current index is missing a target D&D Pack")
    package_root = (ROOT / "packages").resolve()
    dnd_skills = Path(sagasmith_dnd.__file__).resolve().parents[4] / "skills"
    if not dnd_skills.is_dir():
        raise ValueError("installed sagasmith-dnd does not expose its skills directory")
    results: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(
        prefix="sagasmith-dnd-import-evidence-", ignore_cleanup_errors=True
    ) as temp:
        temp_root = Path(temp)
        server = create_server(
            McpConfig(
                home=temp_root / "home",
                database_url=None,
                chroma_url=None,
                chroma_path_override=None,
                dnd_skills_dir=dnd_skills,
                modulegen_skills_dir=temp_root / "modulegen",
                rule_import_roots=(package_root,),
            )
        )
        for ordinal, package_id in enumerate(sorted(target_ids), start=1):
            item = packages[package_id]
            archive = (ROOT / str(item["path"])).resolve()
            if archive.parent != package_root or not archive.is_file():
                raise ValueError(f"indexed archive is outside packages/: {package_id}")
            expected_package, _blobs = loads_content_archive(archive.read_bytes())
            campaign = await _call(
                server,
                "campaign_create",
                {
                    "name": f"Import evidence {ordinal}",
                    "edition": "2014",
                    "idempotency_key": f"evidence-campaign-{ordinal}",
                },
            )
            arguments = {
                "action": "import",
                "payload": {
                    "campaign_id": campaign["id"],
                    "kind": str(item["kind"]),
                    "source_path": str(archive),
                },
                "idempotency_key": f"evidence-import-{ordinal}",
            }
            imported = await _call(server, "content_pack", arguments)
            replayed = await _call(server, "content_pack", arguments)
            if imported != replayed:
                raise ValueError(f"public MCP import is not idempotent: {package_id}")
            stored = dict(imported.get("package") or imported.get("addon") or {})
            if (
                stored.get("id") != package_id
                or stored.get("version") != item["version"]
                or stored.get("checksum") != item["checksum"]
            ):
                raise ValueError(f"public MCP imported a different identity: {package_id}")
            identity_field = "module_id" if str(item["kind"]) == "module" else "addon_id"
            detail_payload = {
                "campaign_id": campaign["id"],
                "kind": str(item["kind"]),
                "version": str(item["version"]),
                "include_package": True,
            }
            if str(item["kind"]) == "module":
                # The module facade's runtime id is generated on import; the
                # finalized Pack identity is therefore retrieved by archive.
                detail_payload["source_path"] = str(archive)
            else:
                detail_payload[identity_field] = package_id
            detail = await _call(
                server,
                "content_pack",
                {
                    "action": "get",
                    "payload": detail_payload,
                },
            )
            detailed_package = dict(
                detail.get("package") or detail.get("module") or detail
            )
            if (
                detailed_package.get("id") != package_id
                or detailed_package.get("version") != item["version"]
                or detailed_package.get("checksum") != item["checksum"]
            ):
                raise ValueError(f"public MCP get returned a different Pack: {package_id}")
            listed = await _call(
                server,
                "content_pack",
                {
                    "action": "list",
                    "payload": {
                        "campaign_id": campaign["id"],
                        "kind": str(item["kind"]),
                    },
                },
            )
            listed_value = (
                listed.get("packages") or listed.get("result") or []
                if isinstance(listed, dict)
                else listed
            )
            listed_items = list(listed_value)
            if str(item["kind"]) == "module":
                listed_match = any(
                    str(entry.get("logical_source_key") or "")
                    == str(expected_package.get("sources", [{}])[0].get("source_key") or "")
                    and str(entry.get("parser_profile") or "") == "content-package"
                    and int(entry.get("scenes") or 0)
                    == len(expected_package.get("content", {}).get("scene_atlas") or [])
                    for entry in listed_items
                    if isinstance(entry, dict)
                )
            else:
                listed_match = any(
                    (entry.get("id") or entry.get("addon_id")) == package_id
                    and (entry.get("checksum") or entry.get("package_checksum"))
                    == item["checksum"]
                    for entry in listed_items
                    if isinstance(entry, dict)
                )
            if not listed_match:
                raise ValueError(f"public MCP list omitted the imported Pack: {package_id}")
            results[package_id] = {
                "id": package_id,
                "kind": str(item["kind"]),
                "checksum": str(item["checksum"]),
                "campaign_id": str(campaign["id"]),
                "idempotent_replay": True,
                "listed_count": len(listed_items),
            }
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--package-id",
        action="append",
        choices=sorted(TARGET_IDS),
        dest="package_ids",
        help="refresh only this current Pack identity; may be repeated",
    )
    args = parser.parse_args()
    target_ids = frozenset(args.package_ids or TARGET_IDS)
    index = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))
    evidence_path = ROOT / "import-evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    refreshed = asyncio.run(_refresh(index, target_ids))
    current = list(evidence.get("dnd") or [])
    evidence["dnd"] = [
        refreshed.get(str(item.get("id") or ""), item) for item in current
    ]
    if set(refreshed) != target_ids:
        raise ValueError("not every target D&D Pack produced import evidence")
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"refreshed": len(refreshed)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
