"""Publish only open-license packages from a complete private content library."""

from __future__ import annotations

import argparse
import copy
import json
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

from sagasmith_core.content_pack import build_content_package, dumps_content_archive
from sagasmith_dnd.content_packages import build_preset_content_package
from sagasmith_dnd.public_library import build_public_library

from preset_packages import current_srd_preset_inputs

PUBLIC_PRESETS = {
    "dnd5e.presets.srd2014": {
        "attribution": (
            "This work includes material taken from the System Reference Document 5.1 "
            '(“SRD 5.1”) by Wizards of the Coast LLC, available at '
            "https://www.dndbeyond.com/srd. The SRD 5.1 "
            "is licensed under CC-BY-4.0."
        ),
        "source_url": "https://www.dndbeyond.com/srd",
    },
    "dnd5e.presets.srd2024": {
        "attribution": (
            "This work includes material from the System Reference Document 5.2.1 "
            '(“SRD 5.2.1”) by Wizards of the Coast LLC, available at '
            "https://www.dndbeyond.com/srd. The SRD 5.2.1 is licensed under "
            "CC-BY-4.0."
        ),
        "source_url": "https://www.dndbeyond.com/srd",
    },
}
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/legalcode"


def _open_srd_preset(
    package: dict, blobs: dict[str, bytes]
) -> tuple[dict, dict[str, bytes]]:
    evidence = PUBLIC_PRESETS[str(package["id"])]
    sources = [
        copy.deepcopy(source)
        for source in package["sources"]
        if str(source.get("authority") or "") == "preset"
    ]
    if len(sources) != 1:
        raise ValueError(f"{package['id']} must have exactly one synthetic SRD preset source")
    source_keys = {str(source["source_key"]) for source in sources}
    asset_keys = {str(source["normalized_document_asset_key"]) for source in sources}
    assets = [
        copy.deepcopy(asset)
        for asset in package["assets"]
        if str(asset["asset_key"]) in asset_keys
    ]
    if len(assets) != len(asset_keys):
        raise ValueError(f"{package['id']} is missing its normalized SRD preset document")
    for asset in assets:
        asset["license"] = "CC-BY-4.0"
        asset["attribution"] = evidence["attribution"]
        asset["source_refs"] = [
            ref for ref in asset["source_refs"] if str(ref["source_key"]) in source_keys
        ]
    actors = copy.deepcopy(list(package["actors"]))
    for actor in actors:
        actor["image"] = None
        provenance = dict(actor.get("provenance") or {})
        provenance["source_refs"] = [
            ref
            for ref in provenance.get("source_refs") or []
            if str(ref["source_key"]) in source_keys
        ]
        actor["provenance"] = provenance
    metadata = copy.deepcopy(dict(package["metadata"]))
    metadata.update(
        {
            "distribution": "public",
            "license": "CC-BY-4.0",
            "attribution": evidence["attribution"],
            "license_evidence": {
                "type": "open_license",
                "license_url": LICENSE_URL,
                "source_url": evidence["source_url"],
            },
        }
    )
    metadata.pop("redistribution_authorization", None)
    result = build_content_package(
        kind="preset",
        package_id=str(package["id"]),
        version=str(package["version"]),
        system_id=str(package["system_id"]),
        manifest=package["manifest"],
        dependencies=[],
        sources=sources,
        assets=assets,
        content_reviews=package["content_reviews"],
        actors=actors,
        content=package["content"],
        metadata=metadata,
    )
    retained_checksums = {str(asset["checksum"]) for asset in assets}
    return result, {key: value for key, value in blobs.items() if key in retained_checksums}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "public" / "content-library",
    )
    args = parser.parse_args()

    packages = []
    archives = {}
    skill_root = WORKSPACE / "SagaSmith-dnd-skills"
    for preset_input in current_srd_preset_inputs(skill_root):
        if not preset_input["cards"]:
            raise ValueError("bundled SRD actor presets are unavailable")
        package, blobs = build_preset_content_package(
            **preset_input,
        )
        package, blobs = _open_srd_preset(package, blobs)
        archive = dumps_content_archive(package, blobs)
        packages.append(package)
        archives[str(package["checksum"])] = archive
    if {package["id"] for package in packages} != set(PUBLIC_PRESETS):
        raise ValueError("private library does not contain both SRD preset packages")
    build_public_library(args.output, packages, archives=archives)
    counts = Counter(str(package["kind"]) for package in packages)
    audit = {
        "schema": "sagasmith.content-library-audit.v1",
        "visibility": "public",
        "counts": dict(sorted(counts.items())),
        "total": len(packages),
        "images": 0,
        "excluded_private_packages": 28,
        "policy": (
            "Only open-license SRD content is published. User-supplied commercial "
            "documents and extracted artwork remain in the private library."
        ),
    }
    (args.output / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"packages": len(packages), "counts": counts}, default=dict))


if __name__ == "__main__":
    main()
