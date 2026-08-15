"""Replace the repository collection with one validated migration output."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "content-library"
COPIED_FILES = {
    "VALIDATION.md",
    "index.json",
    "migration-report.json",
    "validation-summary.json",
}


def _portable(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\\", "/")
    if isinstance(value, list):
        return [_portable(item) for item in value]
    if isinstance(value, dict):
        return {key: _portable(item) for key, item in value.items()}
    return value


def _write_portable_json(source: Path, target: Path) -> None:
    value = json.loads(source.read_text(encoding="utf-8"))
    target.write_text(
        json.dumps(_portable(value), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    output = OUTPUT.resolve()
    if output.parent != REPO.resolve():
        raise ValueError("refusing output outside the repository")
    required = COPIED_FILES | {"packages", "import-validation-final2"}
    missing = sorted(name for name in required if not (source / name).exists())
    if missing:
        raise FileNotFoundError(f"migration output is incomplete: {missing}")

    report = json.loads((source / "migration-report.json").read_text(encoding="utf-8"))
    if len(report.get("packages") or []) != 46:
        raise ValueError("current private library requires exactly 46 Packs")
    if report.get("unresolved_external_dependencies"):
        raise ValueError("current private library has unresolved dependencies")

    if output.exists():
        shutil.rmtree(output)
    (output / "packages").mkdir(parents=True)
    for path in sorted((source / "packages").glob("*.sagasmith-pack")):
        shutil.copy2(path, output / "packages" / path.name)
    for name in sorted(COPIED_FILES):
        source_path = source / name
        target = output / name
        if source_path.suffix == ".json":
            _write_portable_json(source_path, target)
        else:
            shutil.copy2(source_path, target)
    _write_portable_json(
        source / "import-validation-final2" / "evidence.json",
        output / "import-evidence.json",
    )
    print(json.dumps({"packages": 46, "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
