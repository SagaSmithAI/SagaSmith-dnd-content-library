# SagaSmith Current Content Pack Library

[Website](https://sagasmithai.github.io/library) · [Platform overview](https://github.com/SagaSmithAI/.github/blob/main/profile/README.md) · [Hosted service](https://github.com/SagaSmithAI/SagaSmith-service) · [Machine-readable index](content-library/index.json)

Public, checksum-verified catalog and archive storage for the current SagaSmith
D&D 5e and Call of Cthulhu 7e Content Packs. Repository visibility is not a
content license: every Pack, source document, and embedded asset retains its own
license, attribution, and distribution restrictions. Download, import, or
redistribute only content you are authorized to use.

The current collection contains 46 immutable Packs:

- D&D: 21 addons, 2 core-rule Packs, 18 modules, and 2 actor presets.
- CoC: 1 core-rule Pack and 2 modules.

`content-library/index.json` is the current machine-readable integrity and
discovery index; presence in the index does not establish redistribution rights.
`content-library/migration-report.json` records the source version and checksum
for each migrated identity, all superseded archives, and the seven unfinalized
module inputs that were intentionally refused. Pack archives are stored through
Git LFS under `content-library/packages/`.

Finalized source Packs are immutable. Updating this library means publishing a
new Pack version and replacing the current collection; it does not rewrite the
source archive or preserve a parallel legacy protocol.

Validate a checkout after fetching LFS objects:

```powershell
python scripts/validate_library.py
```

The validator checks archive SHA-256 and sizes, descriptor identities, every
embedded blob, required dependency closure, portable index paths, and the exact
current system/kind counts.

The repository tooling is Apache-2.0. Each Pack and embedded asset retains its
own license, attribution, and distribution metadata; the repository license
does not grant redistribution rights for Pack content.
