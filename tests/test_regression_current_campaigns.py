from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import threading
import time
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "regression_current_campaigns.py"


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("regression_current_campaigns", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "max_cycles": 2,
        "parallelism": 2,
        "skip_restart": True,
        "fail_fast": False,
        "output_dir": tmp_path,
        "resume": False,
        "campaign": [],
        "inventory_only": False,
        "service_repo": tmp_path,
        "base_url": "http://127.0.0.1:8080",
        "timeout_seconds": 30,
        "tool_audit": tmp_path / "tool-audit.jsonl",
        "skip_runtime_refresh": True,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _unit(identifier: str) -> dict[str, object]:
    return {
        "id": identifier,
        "system_id": "dnd5e",
        "logical_campaign_line": identifier,
    }


def _report(unit: dict[str, object]) -> dict[str, object]:
    return {
        "unit": unit,
        "campaign_id": f"campaign-{unit['id']}",
        "complete": True,
        "gaps": [],
        "tool_coverage": {"tool_calls": 1},
    }


def test_parallel_scheduler_overlaps_campaigns_and_stabilizes_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    units = [_unit("campaign-b"), _unit("campaign-a")]
    monkeypatch.setattr(runner, "_inventory", lambda: units)
    monkeypatch.setattr(runner, "_refresh_runtime", lambda args: {})
    monkeypatch.setattr(runner, "_wait_ready", lambda client: {})

    def register(client, credentials):
        client.client.cookies.set("session", client.actor)
        return {"id": client.actor}, "registered"

    monkeypatch.setattr(runner, "_register_or_login", register)
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def run_isolated(args, unit, owner_user, player_user, owner_cookies, player_cookies):
        nonlocal active, maximum_active
        assert owner_cookies == {"session": "owner"}
        assert player_cookies == {"session": "player"}
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.1)
        with lock:
            active -= 1
        return _report(unit)

    monkeypatch.setattr(runner, "_run_isolated_unit", run_isolated)

    assert runner._run(_args(tmp_path)) == 0
    assert maximum_active == 2
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["parallelism"] == 2
    assert [item["id"] for item in summary["campaigns"]] == [
        "campaign-a",
        "campaign-b",
    ]


def test_parallel_scheduler_rejects_in_process_restart(tmp_path: Path) -> None:
    runner = _load_runner()
    with pytest.raises(ValueError, match="require --skip-restart"):
        runner._run(_args(tmp_path, skip_restart=False))
