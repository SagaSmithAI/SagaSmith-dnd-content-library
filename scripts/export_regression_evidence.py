"""Export an allow-listed, credential-free long-regression evidence record."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "sagasmith.content-library-regression-evidence/v1"
FORBIDDEN_KEYS = {
    "access_token",
    "accounts",
    "authorization",
    "client_secret",
    "code_verifier",
    "cookie",
    "cookies",
    "oauth_state",
    "password",
    "refresh_token",
    "session",
    "session_id",
}
FORBIDDEN_VALUES = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(?:access|refresh)[_-]?token\b"),
    re.compile(r"(?i)\boauth[_ -]?(?:code|state|verifier)\b"),
    re.compile(r"(?i)\bset-cookie\b"),
    re.compile(r"(?i)\b(?:gh[opusr]|github_pat)_[a-z0-9_]+"),
    re.compile(r"(?i)\bsk-[a-z0-9_-]{8,}"),
    re.compile(r"(?i)(?:[a-z]:\\users\\|/home/|/users/)[^\s\"']+"),
)


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _checks(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict):
        return {}
    return {str(key): bool(item) for key, item in sorted(value.items())}


def _gaps(value: Any) -> list[str]:
    return [str(item) for item in _list(value)]


def _public_campaign(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(value.get("id", "")),
        "system_id": str(value.get("system_id", "")),
        "logical_campaign_line": str(value.get("logical_campaign_line", "")),
        "complete": bool(value.get("complete")),
        "gaps": _gaps(value.get("gaps")),
        "tool_calls": int(value.get("tool_calls") or 0),
    }


def _public_module(value: dict[str, Any]) -> dict[str, Any]:
    endings = []
    for ending in _list(value.get("declared_endings")):
        if not isinstance(ending, dict):
            continue
        endings.append(
            {
                key: ending[key]
                for key in ("id", "status", "title")
                if key in ending and isinstance(ending[key], (str, int, float, bool))
            }
        )
    return {
        "id": str(value.get("id", "")),
        "version": str(value.get("version", "")),
        "checksum": str(value.get("checksum", "")),
        "archive_sha256": str(value.get("archive_sha256", "")),
        "system_id": str(value.get("system_id", "")),
        "logical_campaign_line": str(value.get("logical_campaign_line", "")),
        "title": str(value.get("title", "")),
        "declared_endings": endings,
    }


def _public_coverage(value: Any, *, include_counts: bool) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    result: dict[str, Any] = {
        "complete": bool(source.get("complete")),
        "checks": _checks(source.get("checks")),
        "gaps": _gaps(source.get("gaps")),
    }
    if include_counts:
        for key in ("tool_calls", "successful_tool_calls", "tool_errors"):
            result[key] = int(source.get(key) or 0)
    else:
        result["event_count"] = int(source.get("event_count") or 0)
        result["event_types"] = sorted(str(item) for item in _list(source.get("event_types")))
    return result


def _public_report(value: dict[str, Any]) -> dict[str, Any]:
    unit = value.get("unit") if isinstance(value.get("unit"), dict) else {}
    return {
        "module_id": str(unit.get("id", "")),
        "module_version": str(unit.get("version", "")),
        "module_checksum": str(unit.get("checksum", "")),
        "complete": bool(value.get("complete")),
        "gaps": _gaps(value.get("gaps")),
        "service_coverage": _public_coverage(
            value.get("service_coverage"), include_counts=False
        ),
        "tool_coverage": _public_coverage(value.get("tool_coverage"), include_counts=True),
    }


def _public_runtime(value: dict[str, Any]) -> dict[str, Any]:
    sources = value.get("workspace_sources")
    if not isinstance(sources, dict):
        sources = {}
    components: dict[str, dict[str, Any]] = {}
    for name, source in sorted(sources.items()):
        if not isinstance(source, dict):
            continue
        components[str(name)] = {
            "revision": str(source.get("revision", "")),
            "branch": str(source.get("branch", "")),
            "committed_at": str(source.get("committed_at", "")),
            "dirty": bool(source.get("dirty")),
        }
    return {
        "generated_at": str(value.get("generated_at", "")),
        "refresh_skipped": bool(value.get("skipped")),
        "components": components,
    }


def build_evidence(run_dir: Path) -> dict[str, Any]:
    summary = _object(run_dir / "summary.json")
    inventory = _object(run_dir / "inventory.json")
    runtime = _object(run_dir / "runtime-refresh.json")
    selected = [str(item) for item in _list(summary.get("selected"))]
    modules = {
        str(item.get("id")): item
        for item in _list(inventory.get("modules"))
        if isinstance(item, dict)
    }
    reports = []
    for path in sorted((run_dir / "campaigns").glob("*/campaign-report.json")):
        reports.append(_public_report(_object(path)))
    evidence = {
        "schema": SCHEMA,
        "generated_at": str(summary.get("generated_at", "")),
        "model": str(summary.get("model", "")),
        "redaction": {
            "profile": "credentials-and-session-state-v1",
            "allow_listed_fields_only": True,
            "authentication_state_included": False,
            "account_data_included": False,
            "raw_http_included": False,
        },
        "runtime": _public_runtime(runtime),
        "inventory": {
            "selected": [_public_module(modules[item]) for item in selected if item in modules],
            "explicit_exclusions": [
                {
                    "id": str(item.get("id", "")),
                    "reason": str(item.get("reason", "")),
                }
                for item in _list(inventory.get("explicit_exclusions"))
                if isinstance(item, dict)
            ],
        },
        "result": {
            "parallelism": int(summary.get("parallelism") or 0),
            "complete": bool(summary.get("complete")),
            "campaigns": [
                _public_campaign(item)
                for item in _list(summary.get("campaigns"))
                if isinstance(item, dict)
            ],
            "reports": reports,
        },
    }
    validate_evidence(evidence)
    return evidence


def _scan(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in FORBIDDEN_KEYS:
                raise ValueError(f"forbidden authentication field at {path}.{key}")
            _scan(item, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _scan(item, f"{path}[{index}]")
        return
    if isinstance(value, str):
        for pattern in FORBIDDEN_VALUES:
            if pattern.search(value):
                raise ValueError(f"sensitive value at {path}")


def validate_evidence(value: dict[str, Any]) -> None:
    if value.get("schema") != SCHEMA:
        raise ValueError("unsupported regression evidence schema")
    redaction = value.get("redaction")
    if not isinstance(redaction, dict) or not redaction.get("allow_listed_fields_only"):
        raise ValueError("regression evidence must use the allow-list export")
    for key in (
        "authentication_state_included",
        "account_data_included",
        "raw_http_included",
    ):
        if redaction.get(key) is not False:
            raise ValueError(f"regression evidence must declare {key}=false")
    _scan(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    evidence = build_evidence(args.run_dir.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
