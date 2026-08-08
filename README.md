# SagaSmith D&D Content Library

Public, checksum-verified portable content for SagaSmith D&D 5e:

- built-in 2014 and 2024 preset actor/monster packs;
- complete addon packs generated from the available rulebook corpus;
- imported campaign and guide module packs with Scene Atlas, assets, content
  reviews, and portable actor cards.

Browse the deployed catalog at
<https://sagasmithai.github.io/SagaSmith-dnd-content-library/> or import the
machine-readable index from
<https://sagasmithai.github.io/SagaSmith-dnd-content-library/content-library/index.json>.

Every published JSON envelope is rebuilt with canonical serialization and a
fresh checksum, then passed through SagaSmith's public-license and package
schema validators. `public/content-library/audit.json` records the selected
source artifacts and generated identities.

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
