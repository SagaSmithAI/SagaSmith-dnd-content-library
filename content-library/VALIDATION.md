# Current Pack migration validation

This directory is the authoritative result of the 2026-08-16 offline Pack
migration plus the 2026-08-30 D&D actor-card compatibility refresh. Finalized
source archives were not overwritten; migrated Packs have new patch versions
and new content checksums.

- 46 current Pack identities: 43 D&D and 3 CoC.
- 41 identities were migrated and 5 already-current identities were retained.
- 4 official D&D addon Packs with legacy actor-card encodings were subsequently
  republished as `1.0.2` with canonical current sheets and notes.
- 59 older finalized archives are recorded as superseded.
- 7 unfinalized D&D module inputs were refused because Agent finalization is
  absent; they are listed in `migration-report.json` and were not presented as
  playable Packs.
- 46 archives (1,062,812,157 bytes) passed archive loading, blob integrity,
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
