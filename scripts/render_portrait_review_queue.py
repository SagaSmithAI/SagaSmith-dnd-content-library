"""Render exact private source pages needed for portrait crop review."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pymupdf
from rebuild_catalog import (
    WORKSPACE,
    _book_source_paths,
    _load_archives,
    _module_source_paths,
    _publish,
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "source"


def _source_path_index(
    *,
    rulebook_pack_dir: Path,
    semantic_input_dir: Path,
    books: Path,
    campaigns: Path,
) -> dict[str, Path]:
    result: dict[str, Path] = {}
    book_paths = sorted(books.rglob("*.pdf"))
    for raw_package, _blobs in _load_archives(rulebook_pack_dir).values():
        package = _publish(raw_package)
        result.update(_book_source_paths(package, book_paths))
    for raw_package, _blobs in _load_archives(
        semantic_input_dir,
        validate=False,
        kinds={"module"},
    ).values():
        package = _publish(raw_package)
        result.update(_module_source_paths(package, campaigns))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("queue", type=Path)
    parser.add_argument("--rulebook-pack-dir", type=Path, required=True)
    parser.add_argument(
        "--semantic-input-dir",
        type=Path,
        default=WORKSPACE / "tmp" / "unified-content-build-cache",
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
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scale", type=float, default=1.6)
    args = parser.parse_args()

    queue = json.loads(args.queue.read_text(encoding="utf-8"))
    if set(queue) != {"schema", "reviews"} or queue["schema"] != (
        "sagasmith.portrait-review-queue.v1"
    ):
        raise ValueError("unsupported portrait review queue")
    source_paths = _source_path_index(
        rulebook_pack_dir=args.rulebook_pack_dir,
        semantic_input_dir=args.semantic_input_dir,
        books=args.books,
        campaigns=args.campaigns,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    rendered: dict[tuple[str, int], dict] = {}
    documents: dict[Path, pymupdf.Document] = {}
    try:
        for review_key, review in sorted(dict(queue["reviews"]).items()):
            review_pages = []
            for source in review.get("sources") or []:
                source_key = str(source.get("source_key") or "")
                page_number = source.get("page")
                source_path = source_paths.get(source_key)
                if (
                    source_path is None
                    or not isinstance(page_number, int)
                    or isinstance(page_number, bool)
                ):
                    continue
                identity = (source_key, page_number)
                record = rendered.get(identity)
                if record is None:
                    document = documents.get(source_path)
                    if document is None:
                        document = pymupdf.open(source_path)
                        documents[source_path] = document
                    if page_number < 1 or page_number > document.page_count:
                        raise ValueError(f"portrait source page is out of range: {identity}")
                    page = document[page_number - 1]
                    pixmap = page.get_pixmap(
                        matrix=pymupdf.Matrix(args.scale, args.scale),
                        alpha=False,
                    )
                    filename = (
                        f"{_slug(source_key)[:120]}--p{page_number:04d}.png"
                    )
                    output_path = args.output / filename
                    pixmap.save(output_path)
                    record = {
                        "source_key": source_key,
                        "page": page_number,
                        "source_path": str(source_path.resolve()),
                        "preview": filename,
                        "page_bounds": [
                            float(page.rect.x0),
                            float(page.rect.y0),
                            float(page.rect.x1),
                            float(page.rect.y1),
                        ],
                        "preview_size": [pixmap.width, pixmap.height],
                    }
                    rendered[identity] = record
                review_pages.append(record)
            review["previews"] = review_pages
            review["review_key"] = review_key
        index = {
            "schema": "sagasmith.portrait-review-previews.v1",
            "reviews": queue["reviews"],
        }
        (args.output / "index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    finally:
        for document in documents.values():
            document.close()


if __name__ == "__main__":
    main()
