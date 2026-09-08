# Current Pack migration validation

This directory is the authoritative result of the 2026-08-16 offline Pack
migration plus the 2026-08-30 D&D actor-card compatibility refresh. Finalized
source archives were not overwritten; migrated Packs have new patch versions
and new content checksums.

- 46 current Pack identities: 43 D&D and 3 CoC.
- 41 identities were migrated and 5 already-current identities were retained.
- 5 official D&D addon Packs with legacy actor-card encodings were subsequently
  republished as `1.0.2` with canonical current sheets and notes.
- 5 official D&D addon Packs were subsequently republished with the runtime
  repair steps recorded in `index.json`: Eberron `1.0.8-local.infusion-source.2`,
  Ravnica `1.0.3-local.subclass-grants.1`, SCAG `1.0.5-local.subclass-grants.1`,
  Tasha's `1.0.1-local.artificer-context.1`, and Wayfinder's Guide
  `1.0.1-local.artificer-context.1`.
- 70 superseded archive records are recorded in `migration-report.json`, with 7
  finalized archives retained for audit and rollback.
- 7 unfinalized D&D module inputs were refused because Agent finalization is
  absent; they are listed in `migration-report.json` and were not presented as
  playable Packs.
- 46 archives (1,062,814,956 bytes) passed archive loading, blob integrity,
  generic Core validation, system validation, report-hash matching, and closed
  required top-level dependency checks.
- All 1,807 module scenes use the current visibility vocabulary: 1,537
  `restricted` and 270 `group`.
- All 43 D&D Packs and all 3 CoC Packs passed the real public MCP
  get/import/list flow plus idempotent retry in fresh databases.
- Both import databases passed SQLite `quick_check` and foreign-key checks and
  are at the sole Alembic head `20260815_33`.
- Full `pytest` and Ruff checks passed in `sagasmith-core` and `sagasmith-dnd`;
  the focused D&D MCP content-package regression suite also passed.

Machine-readable migration details are in `migration-report.json` and
`index.json`. Current public-facade get/import/list and idempotent retry evidence
is in `import-evidence.json`.
