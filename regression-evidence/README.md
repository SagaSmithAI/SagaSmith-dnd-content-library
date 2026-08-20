# Long-regression evidence

This directory stores the public, machine-readable evidence exported from the
content library's Agent-origin full-chain campaign regression.

Only files produced by `scripts/export_regression_evidence.py` may be committed.
Raw run directories, account records, cookies, authorization headers, OAuth
login state, browser/session storage, HTTP traces, and Agent workspaces must
never be copied here or uploaded as repository artifacts.

Each JSON record contains an explicit redaction declaration and is checked by
`scripts/validate_regression_evidence.py` in GitHub Actions.
