# SagaSmith D&D Content Library

Checksum-verified unified content tooling for SagaSmith D&D 5e:

- built-in 2014 and 2024 preset actor/monster packs;
- complete **local private** addon packs generated from a user's rulebook corpus;
- local private module packages plus downloadable `.sagasmith-pack` archives
  with content-addressed source documents and assets, Scene Atlas,
  play/continuity contracts, catalogs, narrative metadata, and actor cards.

The private build is closed over the current corpus: 18 addons, 3 core-rule
packages, 7 Agent-finalized modules, and 2 preset libraries (30 packages total). Its validator
fails if a rebuild silently drops or reclassifies any one of them. The committed
public catalog contains only the two CC-BY-4.0 SRD preset packages. Commercial
books, adventures, their normalized text, and extracted artwork are never
copied to the public catalog without separate redistribution evidence.

Browse the deployed catalog at
<https://sagasmithai.github.io/SagaSmith-dnd-content-library/> or import the
machine-readable index from
<https://sagasmithai.github.io/SagaSmith-dnd-content-library/content-library/index.json>.

Every published descriptor and archive uses `sagasmith.content-package` v2.
Core rules, addons, modules, and presets share the same physical structure while
retaining distinct activation semantics. Each is rebuilt with canonical
serialization and fresh checksums, then passed through
SagaSmith's package, dependency, blob, D&D semantic, and public-license validators.
The web index publishes both the descriptor checksum and the complete archive
SHA-256/byte size so a client can verify the download before opening it.
Editable drafts remain outside the immutable library. Final source bindings,
review dispositions, correction provenance, and Agent confirmation travel in the
Pack so a decision can be audited and replayed without changing the source. A
module enters the catalog only after the Agent confirms its sourced play profile
and narrative.
Actor images are package assets referenced by static actor cards or
owner-dependent statblock template cards and are never copied into runtime
snapshots. In the private build, normalized text, source documents,
actor images, module maps, and player references remain together in the archive.
Private preset portraits are rebuilt from exact, page-bearing Monster Manual
actor evidence; a 2024 card can reuse 2014 evidence only through a unique name
or reviewed alias. Public SRD presets strip those commercial images and evidence.
Source-distributed maps, player handouts, and character-reference PDFs are kept
as typed auxiliary assets instead of being mislabeled as indexed evidence. In
particular, the Lost Mine and Storm King's Thunder supplemental files travel
with their module packages and retain their corpus-relative logical paths.
The standalone Nillian Hextml map remains editable source material and is not
packaged as a module until an Agent authors and confirms an adventure contract.
No legacy portable JSON or `.sagasmith-module` files are published or accepted.
The private audit records every identity and every image extraction outcome.
An exact source page with no usable illustration is recorded as
`illustration_absent`; an invalid page, missing heading, undersized candidate,
or low-confidence crop is `review_required` and fails the release build. The
private rebuild can consume a local `sagasmith.portrait-reviews.v1` file. Each
entry is keyed by `package-id|actor-or-statblock-card|subject-id` and must either
bind an Agent/human-approved crop to an exact cited source page or explicitly
confirm `illustration_absent`; reviewer identity, note, crop, and review-file
checksum are retained in the private audit. Stale decisions and crops outside
the cited page fail closed. This review file and all commercial crops stay
local and are never copied into the public repository.
The public audit records the 28 private packages excluded by the license gate.
Use `scripts/render_portrait_review_queue.py` on the private queue to render
each cited PDF page with its exact PDF-space bounds. This lets an Agent without
native image input hand the review to a vision-capable subtask or a human,
while the final crop decision remains a small, replayable JSON record.

## Rebuild

First finalize every rulebook through the public MCP workflow, including the
cross-instance import/re-export check. Then rebuild all 30 private packages,
embed each original rulebook/module PDF, and re-extract source-backed portraits.
Finally derive the public SRD-only catalog:

```powershell
& ..\SagaSmith-dnd-mcp\.venv\Scripts\python.exe `
  ..\SagaSmith-dnd-mcp\scripts\regression_rulebooks.py `
  ..\reference\DnD-Books\5e\Books `
  --home ..\tmp\content-source `
  --document-cache ..\tmp\document-cache `
  --content-roundtrip `
  --content-target-home ..\tmp\content-target `
  --addon-output-dir ..\tmp\current-rulebook-packs `
  --output ..\tmp\rulebook-audit.json

& ..\sagasmith-dnd\.venv\Scripts\python.exe `
  scripts\rebuild_catalog.py `
  --rulebook-pack-dir ..\tmp\current-rulebook-packs `
  --portrait-review-file ..\tmp\portrait-reviews.json `
  --portrait-review-output ..\tmp\portrait-review-needed.json

& ..\sagasmith-dnd\.venv\Scripts\python.exe `
  scripts\validate_catalog.py `
  --root ..\tmp\unified-private-content-library

& ..\sagasmith-dnd\.venv\Scripts\python.exe scripts\build_public_catalog.py
```

The repository's software is Apache-2.0. See `NOTICE` and each package's
metadata for content-specific source, attribution, and redistribution terms.
The public gate recognizes the official CC-BY releases of
[SRD 5.1 and SRD 5.2.1](https://www.dndbeyond.com/srd). Wizards' official
[Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy)
explicitly distinguishes fan creations from reposting books or rules content.

Validate the committed static catalog without workspace dependencies:

```powershell
python scripts\validate_catalog.py
```
