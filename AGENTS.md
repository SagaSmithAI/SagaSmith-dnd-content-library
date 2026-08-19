# SagaSmith Content Library Agent Guide

## Scope

This repository is a rights-aware catalog and immutable archive store for
current SagaSmith Content Packs. It is not a rules engine, MCP server, Agent
Skill collection, or license grant.

## Content invariants

- Never add or redistribute a Pack, source, or asset without explicit authority.
- Preserve every Pack checksum, source identity, license, attribution, and
  distribution restriction.
- Finalized Packs are immutable. Corrections publish a new Pack version and
  update the current index; never rewrite an existing archive in place.
- Presence in `content-library/index.json` proves catalog membership and
  integrity only, not permission to use or redistribute the content.
- The D&D and CoC vertical repositories validate system semantics. Their MCP
  `content_pack` facades own runtime import, activation, and removal.
- Do not add code or documentation dependencies on archived standalone MCP,
  Skills, UI, or Module Generator repositories.

## Validation

Fetch Git LFS objects before validating:

```powershell
python scripts/validate_library.py
```

Any index or archive change must pass the validator and retain an auditable
source/version/checksum trail.
