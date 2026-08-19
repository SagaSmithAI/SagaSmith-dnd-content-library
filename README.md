# SagaSmith Current Content Pack Library

[Website](https://sagasmithai.github.io/library) · [Platform overview](https://github.com/SagaSmithAI/.github/blob/main/profile/README.md) · [Hosted service](https://github.com/SagaSmithAI/SagaSmith-service) · [Machine-readable index](content-library/index.json)

Public, checksum-verified catalog and archive storage for the current SagaSmith
D&D 5e and Call of Cthulhu 7e Content Packs. Repository visibility is not a
content license: every Pack, source document, and embedded asset retains its own
license, attribution, and distribution restrictions. Download, import, or
redistribute only content you are authorized to use.

## Producers and consumers

- [`sagasmith-dnd`](https://github.com/SagaSmithAI/sagasmith-dnd) and
  [`sagasmith-coc`](https://github.com/SagaSmithAI/sagasmith-coc) define and
  validate current system-specific Pack semantics.
- Their repository-local MCP servers import, activate, export, and remove Packs
  through the authoritative `content_pack` facade.
- [`SagaSmith-service`](https://github.com/SagaSmithAI/SagaSmith-service) and
  the domain Workbenches may surface this catalog, but the catalog never grants
  runtime permission or content rights.

Former standalone MCP, Skills, UI, and Module Generator repositories are
archived history and are not current producers or consumers.

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

## Full-chain campaign regression

The long campaign regression rebuilds and recreates the hosted stack from the
current sibling `SagaSmith-agent`, `sagasmith-core`, `sagasmith-dnd`,
`sagasmith-coc`, and `sagasmith-narrative` worktrees before it sends any room
actions. The exact source revisions and Docker build/recreate results are saved
as `runtime-refresh.json` in the output directory. The runner supplies an
ephemeral shared authorization-context secret to the refreshed local stack; it
does not write that secret to source or regression artifacts.

The Service's `compose.regression.yaml` overlay selects the current hosted Agent
configuration, including the process-local Narrative MCP and signed principal
context required by the latest domain runtimes.

```powershell
python scripts/regression_current_campaigns.py --output-dir ../.runs/current-campaigns
```

Use `--skip-runtime-refresh` only when the Service stack is managed and refreshed
outside the runner. `--inventory-only` never starts or rebuilds the stack.

Campaigns can run concurrently with isolated HTTP clients and per-campaign logs:

```powershell
python scripts/regression_current_campaigns.py `
  --output-dir ../.runs/current-campaigns-parallel `
  --parallelism 4 --skip-restart
```

Parallel mode requires `--skip-restart`; restart/resume evidence must be gathered
by a separate serial run so one campaign cannot restart the Agent while another
campaign has an in-flight model request.

The repository tooling is Apache-2.0. Each Pack and embedded asset retains its
own license, attribution, and distribution metadata; the repository license
does not grant redistribution rights for Pack content.
