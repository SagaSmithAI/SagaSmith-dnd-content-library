from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_regression_evidence.py"


def _load_exporter() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_regression_evidence", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_exporter_keeps_coverage_and_drops_authentication_state(tmp_path: Path) -> None:
    exporter = _load_exporter()
    _write(
        tmp_path / "summary.json",
        {
            "schema": "source-summary",
            "generated_at": "2026-08-20T00:00:00+00:00",
            "model": "test-model",
            "parallelism": 2,
            "selected": ["dnd.module"],
            "complete": True,
            "campaigns": [
                {
                    "id": "dnd.module",
                    "system_id": "dnd5e",
                    "logical_campaign_line": "module",
                    "campaign_id": "campaign-secret",
                    "complete": True,
                    "gaps": [],
                    "tool_calls": 7,
                }
            ],
        },
    )
    _write(
        tmp_path / "inventory.json",
        {
            "modules": [
                {
                    "id": "dnd.module",
                    "version": "1.0.0",
                    "checksum": "pack-checksum",
                    "archive_sha256": "archive-checksum",
                    "archive_path": "C:\\Users\\example\\private-pack",
                    "system_id": "dnd5e",
                    "logical_campaign_line": "module",
                    "title": "Module",
                    "declared_endings": [{"id": "ending", "title": "Ending"}],
                }
            ],
            "explicit_exclusions": [],
        },
    )
    _write(
        tmp_path / "runtime-refresh.json",
        {
            "generated_at": "2026-08-20T00:00:00+00:00",
            "workspace_sources": {
                "SagaSmith-agent": {
                    "path": "C:\\Users\\example\\SagaSmith-agent",
                    "revision": "abc123",
                    "branch": "main",
                    "committed_at": "2026-08-20T00:00:00+00:00",
                    "dirty": False,
                    "status": [],
                }
            },
        },
    )
    _write(
        tmp_path / "campaigns" / "dnd-module" / "campaign-report.json",
        {
            "unit": {
                "id": "dnd.module",
                "version": "1.0.0",
                "checksum": "pack-checksum",
            },
            "campaign_id": "campaign-secret",
            "account_ids": {"owner": "account-secret"},
            "oauth_state": "login-material-must-not-export",
            "complete": True,
            "gaps": [],
            "service_coverage": {
                "complete": True,
                "checks": {"parallel": True},
                "gaps": [],
                "event_count": 3,
                "event_types": ["agent.completed"],
            },
            "tool_coverage": {
                "complete": True,
                "checks": {"legal_ending_recorded": True},
                "gaps": [],
                "tool_calls": 7,
                "successful_tool_calls": 7,
                "tool_errors": 0,
                "sessions": ["session-secret"],
            },
        },
    )
    _write(
        tmp_path / "accounts.json",
        {"owner": {"password": "login-material-must-not-export"}},
    )

    evidence = exporter.build_evidence(tmp_path)
    serialized = json.dumps(evidence)

    assert evidence["result"]["complete"] is True
    assert evidence["result"]["reports"][0]["tool_coverage"]["tool_calls"] == 7
    assert "login-material-must-not-export" not in serialized
    assert "campaign-secret" not in serialized
    assert "account-secret" not in serialized
    assert "session-secret" not in serialized
    assert "C:\\\\Users" not in serialized


def test_validator_rejects_authentication_fields() -> None:
    exporter = _load_exporter()
    value = {
        "schema": exporter.SCHEMA,
        "redaction": {
            "allow_listed_fields_only": True,
            "authentication_state_included": False,
            "account_data_included": False,
            "raw_http_included": False,
        },
        "password": "not-allowed",
    }
    with pytest.raises(ValueError, match="forbidden authentication field"):
        exporter.validate_evidence(value)
