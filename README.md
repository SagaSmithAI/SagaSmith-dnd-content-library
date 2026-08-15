# SagaSmith Private Content Pack Library

Private, checksum-verified storage for the current SagaSmith D&D 5e and Call of
Cthulhu 7e Content Packs. This repository contains commercial/private source
material and must remain private.

The current collection contains 46 immutable Packs:

- D&D: 21 addons, 2 core-rule Packs, 18 modules, and 2 actor presets.
- CoC: 1 core-rule Pack and 2 modules.

`content-library/index.json` is the current machine-readable index.
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

The repository software is Apache-2.0. Each Pack and embedded asset retains its
own license, attribution, and private-distribution metadata; the repository
license does not grant redistribution rights for Pack content.
