# SagaSmith D&D Content Library

Public, checksum-verified portable content for SagaSmith D&D 5e:

- built-in 2014 and 2024 preset actor/monster packs;
- complete addon packs generated from the available rulebook corpus;
- independent module-pack v2 descriptors plus downloadable
  `.sagasmith-module` archives with content-addressed assets, Scene Atlas,
  play/continuity contracts, catalogs, narrative metadata, actor cards, and
  seven-dimensional readiness.

Browse the deployed catalog at
<https://sagasmithai.github.io/SagaSmith-dnd-content-library/> or import the
machine-readable index from
<https://sagasmithai.github.io/SagaSmith-dnd-content-library/content-library/index.json>.

Every published JSON envelope and module archive is rebuilt with canonical
serialization and fresh component/envelope checksums, then passed through
SagaSmith's public-license, package, dependency, blob, and readiness validators.
The catalog shows honest readiness: an indexed source with unresolved play
profile or narrative blockers is downloadable for review but cannot activate.
The removed module-pack v1 files are not published or accepted.
`public/content-library/audit.json` records selected sources and identities.

## Rebuild

Run from the SagaSmith multi-repository workspace:

```powershell
& ..\SagaSmith-dnd-mcp\.venv\Scripts\python.exe scripts\build_library.py
```

The repository's software is Apache-2.0. See `NOTICE` and each package's
metadata for content-specific source, attribution, and redistribution terms.

Validate the committed static catalog without workspace dependencies:

```powershell
python scripts\validate_catalog.py
```
