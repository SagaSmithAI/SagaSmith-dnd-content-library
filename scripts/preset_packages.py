"""Current SRD preset package inputs for content-library rebuilds."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from sagasmith_dnd.content_actors import (
    DND5E_SYSTEM_ID,
    SRD2014_PRESET_PACK_ID,
    SRD2024_PRESET_PACK_ID,
    build_srd2014_preset_actors,
    build_srd2024_preset_actors,
)

PRESET_PACKAGE_VERSION = "2.1.0"


def _versioned(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = copy.deepcopy(cards)
    for card in result:
        card["version"] = PRESET_PACKAGE_VERSION
    return result


def current_srd_preset_inputs(skill_root: Path) -> list[dict[str, Any]]:
    """Return explicit inputs for the two current actor-card.v3 preset packages."""

    return [
        {
            "package_id": SRD2014_PRESET_PACK_ID,
            "version": PRESET_PACKAGE_VERSION,
            "system_id": DND5E_SYSTEM_ID,
            "title": "D&D 5e SRD 5.1 Actor Presets",
            "cards": _versioned(build_srd2014_preset_actors(skill_root)),
            "metadata": {
                "title": "D&D 5e SRD 5.1 Actor Presets",
                "edition": "2014",
                "distribution": "shareable",
                "license": "CC-BY-4.0",
                "attribution": (
                    "Includes material from the System Reference Document 5.1 by "
                    "Wizards of the Coast LLC, licensed under CC-BY-4.0."
                ),
                "content_kinds": ["npc", "monster"],
            },
            "dependencies": [],
        },
        {
            "package_id": SRD2024_PRESET_PACK_ID,
            "version": PRESET_PACKAGE_VERSION,
            "system_id": DND5E_SYSTEM_ID,
            "title": "D&D 5e SRD 5.2.1 Actor Presets",
            "cards": _versioned(build_srd2024_preset_actors(skill_root)),
            "metadata": {
                "title": "D&D 5e SRD 5.2.1 Actor Presets",
                "edition": "2024",
                "distribution": "shareable",
                "license": "CC-BY-4.0",
                "attribution": (
                    "Includes material from the System Reference Document 5.2.1 by "
                    "Wizards of the Coast LLC, licensed under CC-BY-4.0."
                ),
                "content_kinds": ["npc", "monster"],
            },
            "dependencies": [],
        },
    ]
