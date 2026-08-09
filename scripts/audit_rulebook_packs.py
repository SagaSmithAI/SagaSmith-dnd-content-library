"""Audit the exact semantic identity and D&D ownership of rebuilt rulebook packs."""

from __future__ import annotations

import argparse
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

from sagasmith_core.content_pack import loads_content_archive
from sagasmith_dnd.content_packages import validate_dnd_content_package


def _fold(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _identity_fold(value: object) -> str:
    folded = _fold(value)
    if folded.startswith("the "):
        folded = folded[4:]
    return "".join(character for character in folded if character.isalnum())


def _catalog_sha256(artifacts: list[dict]) -> str:
    identities = sorted(
        (_fold(artifact.get("kind")), _fold(dict(artifact.get("card") or {}).get("name")))
        for artifact in artifacts
    )
    return hashlib.sha256(
        json.dumps(identities, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_review_manifest(path: Path, seen: set[Path] | None = None) -> dict:
    resolved = path.expanduser().resolve()
    seen = set() if seen is None else seen
    if resolved in seen:
        raise ValueError(f"catalog review include cycle: {resolved}")
    seen.add(resolved)
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    documents: dict[str, dict] = {}
    for include in payload.get("includes") or []:
        nested = _load_review_manifest(resolved.parent / str(include), seen)
        for key, value in nested.items():
            if key in documents:
                raise ValueError(f"duplicate reviewed document: {key}")
            documents[key] = value
    for key, value in dict(payload.get("documents") or {}).items():
        if key in documents:
            raise ValueError(f"duplicate reviewed document: {key}")
        documents[key] = dict(value)
    seen.remove(resolved)
    return documents


def _review_by_title(documents: dict[str, dict]) -> dict[str, tuple[str, dict]]:
    result: dict[str, tuple[str, dict]] = {}
    for relative_path, review in documents.items():
        title = Path(str(relative_path).replace("\\", "/")).stem.casefold()
        if title in result:
            raise ValueError(f"multiple reviewed documents share title {title!r}")
        result[title] = (relative_path, review)
    return result


def _suspicious_name(name: str) -> bool:
    single_letter_tokens = re.findall(r"(?<!\w)[A-Z](?!\w)", name)
    return len(single_letter_tokens) >= 2 or "�" in name or "\ufffe" in name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack_dir", type=Path)
    parser.add_argument("--catalog-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-unlocked", action="store_true")
    args = parser.parse_args()

    reviews = _review_by_title(_load_review_manifest(args.catalog_manifest))
    paths = sorted(args.pack_dir.expanduser().resolve().glob("*.sagasmith-pack"))
    errors: list[str] = []
    packages = []
    matched_reviews: set[str] = set()
    for path in paths:
        package, _blobs = loads_content_archive(path.read_bytes())
        package = validate_dnd_content_package(package)
        artifacts = [dict(item) for item in package["content"].get("artifacts") or []]
        title = str(package["manifest"]["title"])
        reviewed = reviews.get(title.casefold())
        if reviewed is None:
            errors.append(f"{package['id']}: no catalog review matches {title!r}")
            relative_path, review = "", {}
        else:
            relative_path, review = reviewed
            matched_reviews.add(title.casefold())
        digest = _catalog_sha256(artifacts)
        expected_digest = review.get("expected_catalog_sha256")
        if expected_digest is None:
            if not args.allow_unlocked:
                errors.append(f"{relative_path or package['id']}: missing expected_catalog_sha256")
        elif expected_digest != digest:
            errors.append(
                f"{relative_path}: catalog digest expected {expected_digest}, actual {digest}"
            )

        kinds = Counter(str(item.get("kind") or "") for item in artifacts)
        expected_counts = {
            str(kind): int(count)
            for kind, count in dict(review.get("expected_counts") or {}).items()
            if int(count)
        }
        if expected_counts and dict(sorted(kinds.items())) != dict(sorted(expected_counts.items())):
            errors.append(
                f"{relative_path}: artifact counts differ: "
                f"expected={expected_counts}, actual={dict(kinds)}"
            )

        subclasses: dict[str, set[str]] = {}
        class_names = {
            _identity_fold(dict(artifact.get("card") or {}).get("name"))
            for artifact in artifacts
            if artifact.get("kind") == "class"
        }
        suspicious_names = []
        for artifact in artifacts:
            card = dict(artifact.get("card") or {})
            name = str(card.get("name") or "")
            if not card.get("source_fragment") and _suspicious_name(name):
                suspicious_names.append(name)
            if artifact.get("kind") == "subclass":
                subclasses.setdefault(_identity_fold(name), set()).add(
                    _fold(card.get("class_name"))
                )
        for artifact in artifacts:
            if artifact.get("kind") != "feature":
                continue
            card = dict(artifact.get("card") or {})
            feature_name = _identity_fold(card.get("name"))
            subclass_name = _identity_fold(card.get("subclass_name"))
            if subclass_name and subclass_name == feature_name:
                errors.append(
                    f"{relative_path}: feature {card.get('name')!r} incorrectly "
                    "uses its own name as subclass ownership"
                )
            if subclass_name and subclass_name in class_names and subclass_name not in subclasses:
                errors.append(
                    f"{relative_path}: feature {card.get('name')!r} binds class "
                    f"{card.get('subclass_name')!r} as a subclass"
                )
            if not subclass_name or subclass_name not in subclasses:
                continue
            class_name = _fold(card.get("class_name"))
            if class_name not in subclasses[subclass_name]:
                errors.append(
                    f"{relative_path}: feature {card.get('name')!r} binds "
                    f"{card.get('class_name')!r}/{card.get('subclass_name')!r}, "
                    f"but subclass owner is {sorted(subclasses[subclass_name])}"
                )
        if suspicious_names:
            errors.append(
                f"{relative_path}: suspicious reviewed card identities: "
                + ", ".join(sorted(set(suspicious_names)))
            )
        packages.append(
            {
                "id": package["id"],
                "title": title,
                "document": relative_path,
                "checksum": package["checksum"],
                "catalog_sha256": digest,
                "expected_catalog_sha256": expected_digest,
                "artifact_counts": dict(sorted(kinds.items())),
                "actors": len(package["actors"]),
                "transcription_repairs": sum(
                    len(dict(item.get("card") or {}).get("transcription_repairs") or [])
                    for item in artifacts
                ),
            }
        )

    if len(paths) != 21:
        errors.append(f"expected 21 rulebook packages, found {len(paths)}")
    unmatched_reviews = sorted(set(reviews) - matched_reviews)
    if unmatched_reviews:
        errors.append("catalog reviews have no rebuilt package: " + ", ".join(unmatched_reviews))
    report = {
        "schema": "sagasmith.rulebook-pack-audit.v1",
        "complete": not errors,
        "package_count": len(paths),
        "packages": packages,
        "errors": errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"packages": len(paths), "errors": len(errors)}))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
