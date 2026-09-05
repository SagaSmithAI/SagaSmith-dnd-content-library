# Local SCAG checksum repair

`republish_scag_definition_checksum.py` retains its original filename, but it
does **not** publish a library. It repairs an explicitly supplied, authorized
local SCAG 1.0.3 archive into a new local 1.0.4 archive. It does not change the
repository's current index, migration report, validation summary, or import
evidence. The existing public collection remains at 1.0.3; this tool alone does
not resolve the publication requirement in issue #18.

Use a Python environment containing the current SagaSmith Core and DND domain
packages, and create a private output directory outside this repository first:

```sh
python scripts/republish_scag_definition_checksum.py \
  --source /authorized/library/scag-1.0.3.sagasmith-pack \
  --output /private/repaired/scag-1.0.4.sagasmith-pack
```

The input must match the pinned archive SHA-256 and size. The tool recomputes
the inner definition checksum, cross-checks the runtime checksum algorithm,
rebuilds and validates the package, and checks the complete expected output
archive identity. Embedded source assets, artifacts, and mechanics are unchanged.
Input/output paths containing links or reparse points are rejected. The tool
never replaces an existing destination: an exact existing output is accepted
only after rebuilding and validating the input again. A different output fails.
Writing uses an exclusive hard link from a fully written temporary file;
filesystems without hard-link support fail without an overwrite fallback.

The result explicitly reports `published: false` and `import_verified: false`.
No campaign ID, import receipt, or successful runtime replay is inferred from a
new checksum. Import/activation and any distribution require separate authority
and real runtime verification. A local repair does not grant content rights.

## Validation boundaries

```sh
python -m pytest tests/test_scag_definition_checksum.py -q
```

The ordinary tests use synthetic inputs for checksum, validator, output conflict,
failure, and path-safety behavior. Their injected builder is **not** evidence of
real archive reconstruction. One separate real-input test runs when
`SAGASMITH_SCAG_SOURCE_ARCHIVE` names the authorized 1.0.3 input. Without that
explicit input only that test is skipped. Once configured, a missing file,
dependency, wrong archive, or changed algorithm fails instead of being skipped.

The real test uses production rebuilding and verifies the exact output hash,
the unchanged input and blob bytes, unchanged artifacts/mechanics, and the
independently recomputed definition checksum. Its output stays in pytest's
temporary directory and is never committed or added to the library index.
