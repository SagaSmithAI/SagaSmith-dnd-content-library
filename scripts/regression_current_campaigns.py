"""Exercise every current module Pack through the real SagaSmith Service chain.

The content-library index is the inventory authority. The runner uses two real
Service accounts and only public HTTP/SSE endpoints to create campaigns, request
and approve membership, submit room actions, observe Agent replies, and resume
after a Service/Agent restart. A host-mounted nanobot audit supplies the second
evidence plane proving that the Service-hosted Luna Agent used native Skills and
D&D/CoC MCP tools rather than merely narrating success.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO.parent
LIBRARY = REPO / "content-library"
SERVICE_REPO = WORKSPACE / "SagaSmith-service"
DESCRIPTOR = "package.sagasmith.json"
MODEL = "openai-codex/gpt-5.6-luna"
SERVICE_PACK_ROOT = "/srv/sagasmith/content-library/packages"
PREFIXES = ("mcp_sagasmith_dnd_", "mcp_sagasmith_coc_")
COMPOSE_FILES = (
    "compose.yaml",
    "compose.workspace.yaml",
    "compose.regression.yaml",
    "secrets/compose.lan.yaml",
)
BUILD_SERVICES = ("api", "module-worker", "dnd-mcp", "coc-mcp", "agent")
WORKSPACE_COMPONENTS = (
    "SagaSmith-agent",
    "sagasmith-core",
    "sagasmith-dnd",
    "sagasmith-coc",
    "sagasmith-narrative",
)
_COMPOSE_ENVIRONMENT = os.environ.copy()
_COMPOSE_ENVIRONMENT.setdefault(
    "SAGASMITH_AUTH_CONTEXT_SECRET", secrets.token_urlsafe(48)
)


class ApiFailure(RuntimeError):
    """A public Service request returned a non-success response."""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--campaign", action="append", default=[])
    parser.add_argument("--max-cycles", type=int, default=6)
    parser.add_argument(
        "--parallelism",
        type=int,
        default=1,
        help="number of campaigns to exercise concurrently",
    )
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument(
        "--tool-audit",
        type=Path,
        default=WORKSPACE / ".runs" / "service-agent" / "tool-audit.jsonl",
    )
    parser.add_argument("--service-repo", type=Path, default=SERVICE_REPO)
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--skip-restart", action="store_true")
    parser.add_argument(
        "--skip-runtime-refresh",
        action="store_true",
        help=(
            "use an externally managed Service stack instead of rebuilding and "
            "recreating it from the current sibling SagaSmith worktrees"
        ),
    )
    return parser.parse_args()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _compose_command(*arguments: str) -> list[str]:
    command = ["docker", "compose"]
    for compose_file in COMPOSE_FILES:
        command.extend(("-f", compose_file))
    command.extend(arguments)
    return command


def _run_command(
    command: list[str], *, cwd: Path, timeout: int
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    started = datetime.now(UTC)
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=_COMPOSE_ENVIRONMENT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    result = {
        "command": command,
        "started_at": started.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    return completed, result


def _git_metadata(repository: Path) -> dict[str, Any]:
    if not (repository / ".git").exists():
        raise ValueError(f"required SagaSmith worktree is absent: {repository}")

    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repository,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"git {' '.join(arguments)} failed in {repository}: {message}")
        return completed.stdout.strip()

    status = git("status", "--porcelain=v1", "--untracked-files=normal")
    return {
        "path": str(repository.resolve()),
        "revision": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "committed_at": git("show", "-s", "--format=%cI", "HEAD"),
        "dirty": bool(status),
        "status": status.splitlines(),
    }


def _runtime_sources(service_repo: Path) -> dict[str, dict[str, Any]]:
    workspace = service_repo.resolve().parent
    repositories = {
        "SagaSmith-service": service_repo.resolve(),
        **{name: workspace / name for name in WORKSPACE_COMPONENTS},
        "SagaSmith-dnd-content-library": REPO,
    }
    return {name: _git_metadata(path) for name, path in repositories.items()}


def _refresh_runtime(args: argparse.Namespace) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": "sagasmith.contentlib-runtime-refresh/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "workspace_sources": _runtime_sources(args.service_repo),
        "skipped": bool(args.skip_runtime_refresh),
    }
    report_path = args.output_dir / "runtime-refresh.json"
    if args.skip_runtime_refresh:
        _write_json(report_path, report)
        return report

    timeout = max(int(args.timeout_seconds), 1800)
    build, report["build"] = _run_command(
        _compose_command("build", "--pull", *BUILD_SERVICES),
        cwd=args.service_repo,
        timeout=timeout,
    )
    _write_json(report_path, report)
    if build.returncode != 0:
        raise RuntimeError("failed to rebuild the Service runtime from workspace sources")

    recreate, report["recreate"] = _run_command(
        _compose_command("up", "-d", "--force-recreate", "--remove-orphans"),
        cwd=args.service_repo,
        timeout=timeout,
    )
    _write_json(report_path, report)
    if recreate.returncode != 0:
        raise RuntimeError("failed to recreate the refreshed Service runtime")
    return report


def _safe_id(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not result:
        raise ValueError(f"invalid identifier: {value!r}")
    return result


def _logical_line(package_id: str) -> str:
    if "lost-mine-of-phandelver" in package_id or re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f-]{27,}", package_id
    ):
        return "lost-mine-of-phandelver"
    for value in (
        "descent-into-avernus-zh",
        "storm-kings-thunder",
        "tomb-of-annihilation",
        "tyranny-of-dragons",
        "waterdeep-dragon-heist",
        "alone-against-the-flames",
        "the-lightless-beacon",
    ):
        if value in package_id:
            return value
    return _safe_id(package_id)


def _advancement(manifest: dict[str, Any]) -> str:
    profile = dict(manifest.get("play_profile") or {})
    value = str(dict(profile.get("advancement") or {}).get("recommended") or "")
    return "milestone" if "milestone" in value else "xp"


def _edition(system_id: str, manifest: dict[str, Any]) -> str:
    if system_id == "coc7e":
        return "7e"
    compatibility = dict(manifest.get("compatibility") or {})
    values = [
        *list(compatibility.get("editions") or []),
        compatibility.get("edition"),
        compatibility.get("rules_version"),
    ]
    return "2024" if any("2024" in str(value) for value in values if value) else "2014"


def _scene_summary(content: dict[str, Any]) -> dict[str, Any]:
    atlas = content.get("scene_atlas") or []
    scenes = list(atlas.values()) if isinstance(atlas, dict) else list(atlas)
    compact = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        compact.append(
            {
                key: scene.get(key)
                for key in ("id", "scene_id", "key", "scene_key", "title")
                if scene.get(key) is not None
            }
        )
    return {
        "count": len(compact),
        "opening": compact[0] if compact else {},
        "conclusion": compact[-1] if compact else {},
    }


def _inventory() -> list[dict[str, Any]]:
    index = _read_json(LIBRARY / "index.json")
    modules: list[dict[str, Any]] = []
    for item in index.get("packages") or []:
        if item.get("kind") != "module":
            continue
        archive_path = (LIBRARY / str(item["path"])).resolve()
        raw = archive_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["archive_sha256"]:
            raise ValueError(f"archive checksum mismatch: {archive_path}")
        with zipfile.ZipFile(archive_path) as archive:
            package = json.loads(archive.read(DESCRIPTOR))
        if package.get("checksum") != item.get("checksum"):
            raise ValueError(f"descriptor checksum mismatch: {archive_path}")
        manifest = dict(package.get("manifest") or {})
        content = dict(package.get("content") or {})
        narrative = dict(content.get("narrative") or {})
        system_id = str(package["system_id"])
        relative_archive = archive_path.relative_to(LIBRARY / "packages").as_posix()
        modules.append(
            {
                "id": str(package["id"]),
                "version": str(package["version"]),
                "checksum": str(package["checksum"]),
                "archive_sha256": str(item["archive_sha256"]),
                "archive_path": str(archive_path),
                "service_archive_path": f"{SERVICE_PACK_ROOT}/{relative_archive}",
                "system_id": system_id,
                "logical_campaign_line": _logical_line(str(package["id"])),
                "title": str(manifest.get("title") or package["id"]),
                "edition": _edition(system_id, manifest),
                "advancement_mode": _advancement(manifest),
                "play_profile": manifest.get("play_profile") or {},
                "continuity": manifest.get("continuity") or {},
                "declared_endings": narrative.get("endings") or [],
                "scenes": _scene_summary(content),
            }
        )
    return modules


def _normalize_tool(name: str) -> str:
    for prefix in PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


@lru_cache(maxsize=4096)
def _read_persisted_tool_output(path: str, service_repo: Path) -> str:
    normalized = path.replace("\\", "/")
    if not normalized.startswith("/workspaces/") or "/../" in f"{normalized}/":
        return ""
    completed = subprocess.run(
        _compose_command("exec", "-T", "agent", "cat", normalized),
        cwd=service_repo,
        env=_COMPOSE_ENVIRONMENT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    return completed.stdout if completed.returncode == 0 else ""


def _decode(content: Any, service_repo: Path | None = None) -> Any:
    if not isinstance(content, str):
        return content
    text = content.strip()
    if not text or text.startswith(("Error:", "Error executing tool", "(MCP tool call failed:")):
        return None
    if text.startswith("[tool output persisted]") and service_repo is not None:
        match = re.search(r"^Full output saved to:\s*(/workspaces/\S+)$", text, re.MULTILINE)
        if not match:
            return None
        text = _read_persisted_tool_output(match.group(1), service_repo).strip()
        if not text:
            return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(value, dict) and isinstance(value.get("text"), str):
        try:
            return json.loads(value["text"])
        except json.JSONDecodeError:
            pass
    return value


def _calls(
    audit_path: Path, campaign_id: str, service_repo: Path | None = None
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    if not audit_path.is_file():
        return calls
    for line in audit_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        session_key = str(row.get("session_key") or "")
        if campaign_id not in session_key:
            continue
        results = {
            str(item.get("tool_call_id") or ""): item
            for item in row.get("tool_results") or []
            if isinstance(item, dict)
        }
        for call in dict(row.get("assistant_message") or {}).get("tool_calls") or []:
            function = dict(call.get("function") or {})
            raw_args = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                arguments = {}
            result_row = results.get(str(call.get("id") or ""), {})
            content = result_row.get("content")
            calls.append(
                {
                    "process_id": row.get("process_id"),
                    "session_key": session_key,
                    "tool": _normalize_tool(str(function.get("name") or "")),
                    "arguments": arguments if isinstance(arguments, dict) else {},
                    "result": _decode(content, service_repo),
                    "error": isinstance(content, str)
                    and content.strip().startswith(
                        ("Error:", "Error executing tool", "(MCP tool call failed:")
                    ),
                }
            )
    return calls


def _walk_values(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_values(item)
    else:
        yield value


def _contains(value: Any, expected: Any) -> bool:
    return any(str(item) == str(expected) for item in _walk_values(value))


def _completed_dnd_ending(call: dict[str, Any]) -> bool:
    """Accept only an authoritative, fully verified manifest completion receipt."""
    receipt = call.get("result")
    if not isinstance(receipt, dict):
        return False
    result = receipt.get("result", receipt)
    if not isinstance(result, dict):
        return False
    manifest = result.get("manifest")
    if not isinstance(manifest, dict) or manifest.get("status") != "completed":
        return False
    ending = manifest.get("ending")
    if not isinstance(ending, dict) or ending.get("status") != "completed":
        return False
    if not str(ending.get("achieved_condition_id") or "").strip():
        return False
    verification = ending.get("verification")
    return (
        isinstance(verification, list)
        and bool(verification)
        and all(isinstance(item, dict) and item.get("passed") is True for item in verification)
    )


def _tool_coverage(unit: dict[str, Any], calls: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [call for call in calls if not call["error"] and call["result"] is not None]
    imports = [
        call
        for call in successful
        if call["tool"] in {"content_pack", "content_package"}
        and call["arguments"].get("action") == "import"
        and _contains(call["arguments"], unit["service_archive_path"])
    ]
    import_groups: dict[str, list[dict[str, Any]]] = {}
    for call in imports:
        key = json.dumps(call["arguments"], ensure_ascii=False, sort_keys=True)
        import_groups.setdefault(key, []).append(call)
    def import_identity(call: dict[str, Any]) -> tuple[str, str, str, str]:
        receipt = dict(call.get("result") or {})
        result = dict(receipt.get("result") or receipt)
        package = dict(result.get("package") or result.get("artifact") or {})
        return (
            str(result.get("module_id") or result.get("content_package_id") or ""),
            str(package.get("id") or ""),
            str(package.get("version") or ""),
            str(package.get("checksum") or ""),
        )

    idempotent_import = any(
        len(group) >= 2
        and bool(import_identity(group[0])[0])
        and all(import_identity(group[0]) == import_identity(item) for item in group[1:])
        for group in import_groups.values()
    )
    identity_seen = any(
        _contains(call["result"], unit["id"])
        or _contains(call["result"], unit["checksum"])
        for call in imports
    )
    activated = any(
        call["tool"] in {"content_pack", "content_package"}
        and call["arguments"].get("action") == "activate"
        for call in successful
    )
    queried = any(
        call["tool"] in {"module_query", "module_search", "module_expand"}
        for call in successful
    )
    entered_play = any(
        call["tool"] in {"game_phase", "campaign_change"}
        and (_contains(call["arguments"], "play") or _contains(call["result"], "play"))
        for call in successful
    )
    skill_read = any(call["tool"] == "skill_query" for call in successful)
    if unit["system_id"] == "dnd5e":
        ending = any(
            call["tool"] == "playthrough_manifest"
            and call["arguments"].get("action") in {"verify_ending", "verify-ending"}
            and _completed_dnd_ending(call)
            for call in successful
        )
    else:
        ending_ids = {
            str(item.get("id"))
            for item in unit.get("declared_endings") or []
            if isinstance(item, dict) and item.get("id")
        }
        ending = any(
            call["tool"] == "campaign_event"
            and any(_contains(call["arguments"], ending_id) for ending_id in ending_ids)
            for call in successful
        )
    checks = {
        "native_skill_read": skill_read,
        "exact_pack_imported": bool(imports) and identity_seen,
        "idempotent_import_replayed": idempotent_import,
        "pack_activated": activated,
        "module_source_queried": queried,
        "entered_play": entered_play,
        "legal_ending_recorded": ending,
    }
    return {
        "complete": all(checks.values()),
        "checks": checks,
        "gaps": [key for key, passed in checks.items() if not passed],
        "tool_calls": len(calls),
        "successful_tool_calls": len(successful),
        "tool_errors": sum(1 for call in calls if call["error"]),
        "sessions": sorted({call["session_key"] for call in calls}),
    }


class ServiceClient:
    def __init__(self, base_url: str, timeout: int, log_path: Path, actor: str) -> None:
        origin = base_url.rstrip("/")
        self.actor = actor
        self.log_path = log_path
        self.client = httpx.Client(
            base_url=origin,
            headers={"Origin": origin},
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
        )

    def close(self) -> None:
        self.client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        expected: int | tuple[int, ...],
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        started = time.monotonic()
        response = self.client.request(
            method, path, json=json_body, headers=headers, params=params
        )
        try:
            body: Any = response.json()
        except json.JSONDecodeError:
            body = response.text
        safe_request = dict(json_body or {})
        if "password" in safe_request:
            safe_request["password"] = "<redacted>"
        record = {
            "at": datetime.now(UTC).isoformat(),
            "actor": self.actor,
            "method": method,
            "path": path,
            "status": response.status_code,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "request": safe_request,
            "response": body,
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        allowed = (expected,) if isinstance(expected, int) else expected
        if response.status_code not in allowed:
            raise ApiFailure(
                f"{self.actor} {method} {path}: expected {allowed}, "
                f"got {response.status_code}: {body}"
            )
        return body


def _register_or_login(
    client: ServiceClient, credentials: dict[str, str]
) -> tuple[dict[str, Any], str]:
    try:
        body = client.request(
            "POST", "/api/auth/register", expected=201, json_body=credentials
        )
        return dict(body["user"]), "registered"
    except ApiFailure as error:
        if "409" not in str(error):
            raise
    body = client.request(
        "POST",
        "/api/auth/login",
        expected=200,
        json_body={"email": credentials["email"], "password": credentials["password"]},
    )
    return dict(body["user"]), "logged_in"


def _wait_ready(client: ServiceClient, timeout: int = 180) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            response = client.client.get("/api/ready", timeout=5)
            if response.status_code == 200:
                return dict(response.json())
            last_error = f"HTTP {response.status_code}: {response.text}"
        except httpx.HTTPError as error:
            last_error = str(error)
        time.sleep(1)
    raise RuntimeError(f"SagaSmith Service did not become ready: {last_error}")


def _events_through(
    client: ServiceClient, campaign_id: str, cursor: int
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    with client.client.stream(
        "GET",
        f"/api/campaigns/{campaign_id}/room/events",
        params={"after": 0},
        timeout=httpx.Timeout(30, read=30),
    ) as response:
        if response.status_code != 200:
            raise ApiFailure(f"room events returned {response.status_code}: {response.text}")
        for line in response.iter_lines():
            if not line:
                if current:
                    events.append(current)
                    if int(current.get("id") or 0) >= cursor:
                        break
                    current = {}
                continue
            if line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            value = value.lstrip()
            if field == "id":
                current["id"] = int(value)
            elif field == "event":
                current["event"] = value
            elif field == "data":
                try:
                    current["data"] = json.loads(value)
                except json.JSONDecodeError:
                    current["data"] = value
    return events


def _owner_prompt(unit: dict[str, Any], cycle: int, gaps: list[str]) -> str:
    prompt_unit = {
        key: value
        for key, value in unit.items()
        if key not in {"archive_path", "archive_sha256", "checksum"}
    }
    import_recovery = ""
    if "idempotent_import_replayed" in gaps:
        recovery_key = f"contentlib-exact-import-{hashlib.sha256(unit['id'].encode()).hexdigest()[:12]}-{cycle}"
        import_recovery = (
            "本轮首要恢复任务：丢弃会话历史里所有 source_path 和 import 幂等键。先查询当前 "
            "campaign revision，然后用下列脚本直出的逐字路径与全新键调用 import，并立刻以"
            "完全相同的 action、payload、expected_revision 和 key 重放一次；不得改写路径，"
            "不得继续使用任何旧键。\n"
            f"EXACT_SOURCE_PATH={json.dumps(unit['service_archive_path'], ensure_ascii=False)}\n"
            f"EXACT_IMPORT_IDEMPOTENCY_KEY={json.dumps(recovery_key)}\n"
        )
    skill_instruction = (
        "先用 skill_query 读取 dnd.full；然后必须调用 skill_query(kind=\"asset\", "
        "action=\"read\", identifier=\"dnd:full/skills/dnd-dm/references/"
        "CAMPAIGN_REGRESSION.md\", heading=\"Per-campaign gate\", max_chars=28000) "
        "读取完整 manifest v2 空 Lobby 形状与 source_ref 规则。任何 manifest 写入被拒后，"
        "先重读该精确段落并按完整模板重建；同一房间回合最多尝试两次，禁止盲目重复。"
        "注册 party member 时，hit_points/resources/wallet 必须是对象，equipment 必须是"
        "字符串数组（无装备时用 []），knowledge_scope_actor_id 必须等于 actor_id。若结局"
        "要求等级，先读取 CHAR_CREATION.md 的 Advancement 段；experience_award.awards "
        "条目只用 {character_id, amount, expected_revision}，并在 Lobby 用现有职业、fixed "
        "HP、当前 actor revision 与活动 source_ref 每次只升一级；level_advance payload "
        "只能含 class_name、hp_method、reason、source_ref，不得传 target_level/fixed_hp。"
        "每次晋升后重读角色再继续，最终 ending 的 actor_value path 必须逐字使用 "
        "sheet.progression.level。若 character_query(get) 结果被持久化，立即用 read_file 读取"
        "其完整路径并核对 sheet.progression.level/xp；XP 模式只按权威阈值一次补足到下一"
        "级，不要猜小额反复 award。达到 expected_end_level 后必须停止 award/level_advance，"
        "绝不越级，直接 sync 与 verify_ending。"
        if unit["system_id"] == "dnd5e"
        else "先用 skill_query 读取 CoC full campaign-manager/Keeper Skill 入口。"
    )
    manifest_schema_instruction = (
        "不要猜测 manifest schema。initialize 时 payload.manifest 必须是完整 v2 对象，"
        "且 expected_revision、branch_id、idempotency_key 只放工具调用顶层："
        '{schema_version:2,run_id:<非空>,campaign_line_id:<非空>,module_ids:[<活动 module id>],'
        'status:"lobby",source_refs:[<精确 source_ref>],current:{module_id:"",chapter_id:"",'
        'chapter_title:"",scene_id:"",scene_title:"",objective:""},traversal:{'
        "reachable_scene_ids:[],visited_scene_ids:[],excluded_scenes:[],branch_decisions:[]},"
        'party:{party_size_status:"source_confirmed" 或 "dm_review_completed",'
        "recommended_minimum:<整数或 null>,recommended_maximum:<整数或 null>,selected_size:1,"
        "party_size_review:{},use_pregenerated_first:true,members:[],replacements:[]},npcs:[],"
        "quests:[],clues:[],world_state:{},snapshot_dag:{active_branch_id:\"\","
        'head_snapshot_id:"",nodes:[]},random_stream:{algorithm:"",seed_fingerprint:"",position:0},'
        'ending:{status:"pending",conditions:[],achieved_condition_id:"",verification:[]},'
        "review_blocks:[]}。精确 source_ref 只能含 purpose、asset_path、asset_sha256、"
        "page_start、page_end、heading_path、content_sha256、module_id、scene_id、chunk_id、"
        "excerpt；heading_path 必须是非空字符串数组（即使只有一级也写 [\"标题\"]，绝不"
        "能写单个字符串）；两个 SHA-256 都必须是完整 64 位小写十六进制。注意只有"
        "npcs/quests/clues/review_blocks、party.members/replacements 以及 traversal 下的集合"
        "字段是数组；party.party_size_review 与 world_state 始终是对象 {{}}，不能因笼统的"
        "collection fields 错误改成 []。之后 configure_ending 的"
        "每个 condition 只能含 {id,label,source_ref,all_of}；all_of 每项只能含 "
        "{kind,path,actor_id,fact_key,operator,value}，不得使用 title/checks/condition_type。"
        "不存在 party/add-member facade，也不要搜索它。若没有 PC：在 Lobby 用 "
        "character_create_from(build) 创建一个角色，character_query(get) 读取权威 sheet；"
        "若 Pack 声明 expected_end_level 大于 1，bootstrap 后必须先完成最小合法职业构建："
        "从 result.instance 取 actor；用 character_ability_apply(method=standard_array) 按 "
        "strength=15,dexterity=14,constitution=13,intelligence=12,wisdom=10,charisma=8 "
        "写入六项并重读 revision；character_query(view=catalog,payload 含 campaign_id、"
        "kind=class、query=Fighter)，选择返回的活动 Fighter artifact，按它实际返回的 "
        "selection_requirements 精确填写选择（常见 skills 为 athletics/perception），再用 "
        "character_content_apply 应用该 artifact。绝不能把只有 bootstrap、没有 "
        "sheet.progression.classes 的角色用于升级。"
        "随后 playthrough_manifest(get)，把完整返回对象复制给 action=replace，仅在 "
        "party.members 添加一个含 actor_id、name、status=active、source=generated、"
        "source_asset_path、level、xp、hit_points、resources、wallet、equipment、"
        "knowledge_scope_actor_id 的成员，再 sync；不得用 game_phase 代替登记。"
        if unit["system_id"] == "dnd5e"
        else ""
    )
    ending_instruction = (
        "按 Skill 的精确模板用 playthrough_manifest 配置一个有 Pack 来源证据且机械上"
        "代表结局的条件，通过真实公开状态回执满足条件并 verify_ending。先用公开 "
        "campaign_change(action=\"effect_add\", payload={effect:{id:\"ending-<declared "
        "ending id>\", name:<ending title>, kind:\"module-conclusion\", source:<Pack id@version "
        "+ ending id>, target:{kind:\"campaign\", label:<ending title>}, active:true, "
        "visibility:\"party\", description:<来源定义的完成事实>, metadata:{pack_id:<Pack id>, "
        "pack_version:<version>, content_package_ending_id:<declared ending id>, "
        "source_refs:<该 ending 的 source_refs>}}}, expected_revision=<当前 revision>, "
        "branch_id=<当前 branch>, idempotency_key=<稳定键>) 写入来源定义的结局事实。若该 "
        "id 已存在则不要重复添加。随后 campaign_query(get) 并在 state.world_effects 数组中"
        "按 id 找到真实的从 0 开始索引 N；campaign_state_value 的 path 必须写成 "
        "world_effects.N.metadata.content_package_ending_id 和 world_effects.N.active，绝不能"
        "把数组当对象键访问。用 configure_ending 在相同 condition id 下替换前轮错误条件；"
        "若 Pack 有 expected_end_level，再加 actor_value 的真实等级检查。最后以最新 revision "
        "验证前必须用 module_query(view=\"current\") 确认当前场景存在；若结论场景刚被标成 "
        "completed 导致 current 为空，就用 module_set_progress 把该真实结论 scene_id 设为 "
        "status=\"current\"（不是 active/in_progress/completed），保留它的 module_expand "
        "source_ref，再执行 manifest sync。不要把结论场景完成元数据本身当作 ending check。"
        "调用 verify_ending，并确认 manifest.status=completed、ending.status=completed、"
        "achieved_condition_id 非空且 verification 每项 passed=true。条件不得使用"
        "advisory party.selected_size、ending.status 或任何自指字段冒充战役结局；优先使用"
        "Pack 声明的结局场景/世界事实以及 expected_end_level。"
        if unit["system_id"] == "dnd5e"
        else "用 module_query 找到一个精确 declared ending，完成对应结局场景，并写入 "
        "payload.content_package_ending_id 等于该 ending id 的 campaign_event。"
    )
    return f"""这是由 SagaSmith Service 房间触发的全链路战役回归，第 {cycle} 轮。
你是本房间的 DM/Keeper，模型是 Codex Luna。只使用当前系统原生公开 Skill/MCP 工具；
不得用 shell、文件直读、数据库、内部服务、伪造回执或单纯叙述代替权威工具结果。
{skill_instruction}
{manifest_schema_instruction}

Service 已创建当前 campaign，禁止另建 campaign。不可变 Pack 权威信息如下：
{json.dumps(prompt_unit, ensure_ascii=False)}

当前机器审计仍缺：{json.dumps(gaps, ensure_ascii=False)}。
{import_recovery}
导入时必须从上方 JSON 逐字符复制 service_archive_path，不能用哈希、Pack id 或历史参数
自行拼路径，也不得扩展或缩短文件名前缀。调用前核对 source_path 与
service_archive_path 完全相等。D&D 公共调用形状为
content_pack(action="import", payload={{kind:"module", campaign_id,
source_path:service_archive_path}}, expected_revision, idempotency_key)；CoC 使用对应
content_package 公开 facade。立刻以完全相同参数和相同幂等键重放一次，并核对 Pack id
或 checksum。只激活该返回模块，查询/展开真实开场与结局来源；Pack 已 finalized，禁止
module_draft/rulebook_draft 或修包。

经权威阶段 facade 进入 Play；可执行一个不虚构模块事实的系统机制。{ending_instruction}
如果前轮已有权威回执，先查询后只补缺口，不重复已完成写入。每次阶段/绑定变化后消费
tools/list_changed 并刷新原生工具列表。最后必须按 Service 注入的 room-turn contract
提交公开、可投影的房间回合，简述本轮真实回执与下一步；不得只返回普通文本。
"""


def _player_prompt(unit: dict[str, Any]) -> str:
    return f"""你现在代表已加入同一房间的真实玩家账户，系统为 {unit['system_id']}。
请先通过当前系统原生 MCP 查询权威 campaign/phase/可见状态；不得执行 DM、管理员、
Pack 导入或激活写入，也不得声称控制任何未授予本账户 actor scope 的角色。若已经在
Play，做一个与当前开场证据兼容、无需 actor_id 的安全玩家行动，并在合法时调用一次
系统拥有的无 actor 归属检定/随机机制；若尚未就绪，只报告可见阻塞。该检定的
resolution presentation 默认只对当前 principal 私有：公开房间输出里绝对不能放
resolution_ref、mcp_resolution provenance、resolution_id、骰点或成功/失败结果，也不能
用文字泄露私有回执；只可公开说明玩家已声明安全行动并等待 DM 裁定。最后必须按
Service 注入的 room-turn contract 提交一次公开房间回合，audience 必须逐字使用
{{"kind":"public","actor_refs":[]}}。messages 只使用 narration/prompt 文本块，suggestions
使用空数组；所有 message block 都不得附加 actor_refs，让另一个账户可读取；禁止把
DM 创建的 party member 填进 actor_refs。公开范围不得宽于任何被引用的权威回执。
"""


def _restart_service(args: argparse.Namespace) -> dict[str, Any]:
    _, result = _run_command(
        _compose_command("restart", "api", "agent"),
        cwd=args.service_repo,
        timeout=240,
    )
    return result


def _service_checks(
    *,
    owner_user: dict[str, Any],
    player_user: dict[str, Any],
    members: list[dict[str, Any]],
    owner_snapshot: dict[str, Any] | None,
    player_snapshot: dict[str, Any] | None,
    events: list[dict[str, Any]],
    idempotent_replay: bool,
    player_action_completed: bool,
    usage: list[dict[str, Any]],
    restarted: bool,
    resumed: bool,
) -> dict[str, Any]:
    sequences = [int(item.get("id") or 0) for item in events]
    event_names = [str(item.get("event") or "") for item in events]
    player_messages = list((player_snapshot or {}).get("messages") or [])
    checks = {
        "two_authenticated_accounts": bool(owner_user.get("id"))
        and bool(player_user.get("id"))
        and owner_user.get("id") != player_user.get("id"),
        "player_joined_room": any(
            item.get("user_id") == player_user.get("id") and item.get("status") == "active"
            for item in members
        ),
        "both_accounts_loaded_snapshot": owner_snapshot is not None
        and player_snapshot is not None,
        "agent_reply_visible_to_player": any(
            item.get("sender_type") == "agent" for item in player_messages
        ),
        "player_action_completed": player_action_completed,
        "room_action_idempotent": idempotent_replay,
        "ordered_room_events": bool(sequences)
        and sequences == sorted(set(sequences))
        and "agent.started" in event_names
        and "agent.completed" in event_names,
        "luna_usage_settled": any(
            "luna" in str(item.get("model") or "").lower() for item in usage
        ),
        "service_agent_restart_resume": restarted and resumed,
    }
    return {
        "complete": all(checks.values()),
        "checks": checks,
        "gaps": [key for key, passed in checks.items() if not passed],
        "event_count": len(events),
        "event_types": sorted(set(event_names)),
    }


def _post_action(
    client: ServiceClient,
    campaign_id: str,
    key: str,
    content: str,
) -> dict[str, Any] | None:
    try:
        return dict(
            _retry_idempotent_request(
                client,
                "POST",
                f"/api/campaigns/{campaign_id}/room/messages",
                expected=200,
                headers={"Idempotency-Key": key},
                json_body={"content": content, "mode": "action"},
            )
        )
    except (ApiFailure, httpx.HTTPError):
        return None


def _retry_idempotent_request(
    client: ServiceClient,
    method: str,
    path: str,
    *,
    expected: int | tuple[int, ...],
    headers: dict[str, str],
    json_body: dict[str, Any] | None = None,
    attempts: int = 5,
) -> Any:
    if not headers.get("Idempotency-Key"):
        raise ValueError("bounded request retry requires an Idempotency-Key")
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return client.request(
                method,
                path,
                expected=expected,
                headers=headers,
                json_body=json_body,
            )
        except (ApiFailure, httpx.HTTPError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(min(2**attempt, 8))
    if last_error is not None:
        raise last_error
    raise RuntimeError("idempotent request retry exhausted without an error")


def _fresh_tool_recovery(
    client: ServiceClient,
    campaign_id: str,
    unit: dict[str, Any],
    gaps: list[str],
) -> dict[str, Any]:
    conversation = dict(
        client.request(
            "POST",
            f"/api/campaigns/{campaign_id}/agent/conversations",
            expected=201,
            json_body={"title": f"Contentlib recovery · {_safe_id(unit['id'])[:80]}"},
        )
    )
    unit_hash = hashlib.sha256(unit["id"].encode()).hexdigest()[:12]
    if "idempotent_import_replayed" in gaps:
        exact_import_key = f"fresh-exact-import-{unit_hash}"
        campaign_literal = json.dumps(campaign_id)
        source_literal = json.dumps(unit["service_archive_path"], ensure_ascii=False)
        key_literal = json.dumps(exact_import_key)
        if unit["system_id"] == "dnd5e":
            import_call = (
                'content_pack(action="import", payload={"kind":"module", '
                f'"campaign_id":{campaign_literal}, "source_path":{source_literal}}}, '
                "expected_revision=REVISION_FROM_QUERY, "
                f"idempotency_key={key_literal})"
            )
        else:
            import_call = (
                f'content_pack(action="import", campaign_id={campaign_literal}, '
                f'data={{"kind":"module", "source_path":{source_literal}}}, '
                "expected_revision=REVISION_FROM_QUERY, "
                f"idempotency_key={key_literal})"
            )
        prompt = f"""这是全新隔离的 SagaSmith Service 工具恢复会话。你具有当前战役 DM 权限。
只使用当前系统原生公开 MCP 工具，不使用 shell、数据库或文件读取，也不做其他战役写入。
CAMPAIGN_ID={json.dumps(campaign_id)}
EXACT_SOURCE_PATH={json.dumps(unit['service_archive_path'], ensure_ascii=False)}
EXACT_IMPORT_KEY={key_literal}

先用 campaign_query 查询当前 revision；必要时用 exposure search/set 暴露 content_pack。
然后逐字调用：{import_call}
立刻把完全相同的 action、参数、expected_revision 和 EXACT_IMPORT_KEY 再调用一次。
source_path 只能逐字符复制 EXACT_SOURCE_PATH，不得用任何哈希、ID、历史或猜测重建。
最后用简短文本报告两次原生工具回执；不得声称未获得的结果。
"""
    else:
        prompt = _owner_prompt(unit, 10_000, gaps).replace(
            "最后必须按 Service 注入的 room-turn contract\n提交公开、可投影的房间回合，",
            "最后用普通文本",
        )
    run_key = f"fresh-tool-recovery-{unit_hash}-{uuid.uuid4().hex[:10]}"
    run = dict(
        _retry_idempotent_request(
            client,
            "POST",
            f"/api/campaigns/{campaign_id}/agent/conversations/{conversation['id']}/messages",
            expected=200,
            headers={"Idempotency-Key": run_key},
            json_body={"content": prompt},
        )
    )
    return {"conversation": conversation, "run": run}


def _run_unit(
    args: argparse.Namespace,
    unit: dict[str, Any],
    owner: ServiceClient,
    player: ServiceClient,
    owner_user: dict[str, Any],
    player_user: dict[str, Any],
) -> dict[str, Any]:
    unit_dir = args.output_dir / "campaigns" / _safe_id(unit["id"])
    unit_dir.mkdir(parents=True, exist_ok=True)
    report_path = unit_dir / "campaign-report.json"
    checkpoint_path = unit_dir / "campaign-state.json"
    prior = _read_json(report_path) if args.resume and report_path.is_file() else {}
    checkpoint = (
        _read_json(checkpoint_path)
        if args.resume and checkpoint_path.is_file()
        else {}
    )
    if prior.get("complete") is True:
        return prior
    campaign_id = str(prior.get("campaign_id") or checkpoint.get("campaign_id") or "")
    unit_hash = hashlib.sha256(unit["id"].encode()).hexdigest()
    run_namespace = str(owner_user["id"]).replace("-", "")[:12]
    campaign_key = f"contentlib-v3-{run_namespace}-{unit_hash[:12]}"
    if not campaign_id:
        campaign = _retry_idempotent_request(
            owner,
            "POST",
            "/api/campaigns",
            expected=201,
            headers={"Idempotency-Key": campaign_key},
            json_body={
                "name": (
                    f"Contentlib · {unit['title']} · {run_namespace}-{unit_hash[:8]}"
                ),
                "description": f"Full-chain Luna regression for {unit['id']}@{unit['version']}",
                "system_id": unit["system_id"],
                "edition": unit["edition"],
                "advancement_mode": unit["advancement_mode"],
                "locale": "zh-CN",
                "visibility": "private",
            },
        )
        campaign_id = str(campaign["id"])
        _write_json(
            checkpoint_path,
            {
                "campaign_id": campaign_id,
                "unit_id": unit["id"],
                "owner_user_id": owner_user["id"],
                "player_user_id": player_user["id"],
                "created_at": datetime.now(UTC).isoformat(),
            },
        )

    members = list(
        owner.request("GET", f"/api/campaigns/{campaign_id}/members", expected=200)
    )
    if not any(
        item.get("user_id") == player_user["id"] and item.get("status") == "active"
        for item in members
    ):
        join = player.request(
            "POST",
            f"/api/campaigns/{campaign_id}/join-requests",
            expected=201,
            json_body={"message": f"full-chain regression {unit['id']}"},
        )
        owner.request(
            "POST",
            f"/api/campaigns/{campaign_id}/join-requests/{join['id']}/decision",
            expected=200,
            json_body={"decision": "approved"},
        )
        members = list(
            owner.request("GET", f"/api/campaigns/{campaign_id}/members", expected=200)
        )
    if not checkpoint_path.is_file():
        _write_json(
            checkpoint_path,
            {
                "campaign_id": campaign_id,
                "unit_id": unit["id"],
                "owner_user_id": owner_user["id"],
                "player_user_id": player_user["id"],
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
    owner_snapshot = dict(
        owner.request("GET", f"/api/campaigns/{campaign_id}/room/snapshot", expected=200)
    )
    player_snapshot = dict(
        player.request("GET", f"/api/campaigns/{campaign_id}/room/snapshot", expected=200)
    )
    cycles: list[dict[str, Any]] = list(
        prior.get("cycles") or checkpoint.get("cycles") or []
    )
    restarted = bool(
        prior.get("restart", {}).get("returncode") == 0
        or checkpoint.get("restarted")
    )
    resumed = bool(
        prior.get("resume_probe", {}).get("passed") or checkpoint.get("resumed")
    )
    idempotent_replay = bool(
        prior.get("idempotent_replay") or checkpoint.get("idempotent_replay")
    )
    player_action_completed = bool(
        prior.get("player_action_completed")
        or checkpoint.get("player_action_completed")
    )

    calls = _calls(args.tool_audit, campaign_id, args.service_repo)
    tool_coverage = _tool_coverage(unit, calls)
    start_cycle = len(cycles) + 1
    cycle_limit = args.max_cycles
    if start_cycle > cycle_limit and (
        not idempotent_replay or not player_action_completed
    ):
        # A resumed run must be able to repair Service evidence even when the
        # previous process reached its per-run Agent-cycle cap.
        cycle_limit = start_cycle
    for cycle in range(start_cycle, cycle_limit + 1):
        started = datetime.now(UTC)
        owner_action_sent = not tool_coverage["complete"] or not idempotent_replay
        response = None
        replay = None
        key = ""
        if owner_action_sent:
            prompt = _owner_prompt(unit, cycle, tool_coverage["gaps"])
            prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:10]
            key = (
                f"reg-{hashlib.sha256(unit['id'].encode()).hexdigest()[:12]}-"
                f"{cycle:03d}-{prompt_hash}"
            )
            response = _post_action(owner, campaign_id, key, prompt)
            if response is not None:
                replay = _post_action(owner, campaign_id, key, prompt)
                response_message = dict(response.get("message") or {})
                replay_message = dict((replay or {}).get("message") or {})
                response_agent_message = dict(response.get("agent_message") or {})
                replay_agent_message = dict((replay or {}).get("agent_message") or {})
                idempotent_replay = bool(
                    replay
                    and replay_message.get("id") == response_message.get("id")
                    and replay_agent_message.get("id") == response_agent_message.get("id")
                )
        cycles.append(
            {
                "cycle": cycle,
                "started_at": started.isoformat(),
                "completed_at": datetime.now(UTC).isoformat(),
                "request_key": key,
                "owner_action_sent": owner_action_sent,
                "completed": not owner_action_sent
                or (
                    response is not None
                    and response.get("agent_message") is not None
                ),
            }
        )

        if not player_action_completed:
            player_prompt = _player_prompt(unit)
            player_key = (
                f"player-{hashlib.sha256(unit['id'].encode()).hexdigest()[:12]}-"
                f"{cycle:03d}-{hashlib.sha256(player_prompt.encode()).hexdigest()[:10]}"
            )
            player_response = _post_action(player, campaign_id, player_key, player_prompt)
            player_action_completed = bool(
                player_response and player_response.get("agent_message") is not None
            )

        if not args.skip_restart and not restarted:
            restart = _restart_service(args)
            _write_json(unit_dir / "restart.json", restart)
            restarted = restart["returncode"] == 0
            if restarted:
                _wait_ready(owner)
                try:
                    owner_me = owner.request("GET", "/api/auth/me", expected=200)
                    player_me = player.request("GET", "/api/auth/me", expected=200)
                    runtime = owner.request(
                        "GET", f"/api/campaigns/{campaign_id}/runtime", expected=200
                    )
                    resumed = bool(owner_me and player_me and runtime)
                except ApiFailure:
                    resumed = False
                _write_json(
                    unit_dir / "resume-probe.json",
                    {"passed": resumed, "checked_at": datetime.now(UTC).isoformat()},
                )

        calls = _calls(args.tool_audit, campaign_id, args.service_repo)
        tool_coverage = _tool_coverage(unit, calls)
        owner_snapshot = dict(
            owner.request(
                "GET", f"/api/campaigns/{campaign_id}/room/snapshot", expected=200
            )
        )
        player_snapshot = dict(
            player.request(
                "GET", f"/api/campaigns/{campaign_id}/room/snapshot", expected=200
            )
        )
        _write_json(
            checkpoint_path,
            {
                "campaign_id": campaign_id,
                "unit_id": unit["id"],
                "owner_user_id": owner_user["id"],
                "player_user_id": player_user["id"],
                "created_at": checkpoint.get("created_at")
                or datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
                "cycles": cycles,
                "idempotent_replay": idempotent_replay,
                "player_action_completed": player_action_completed,
                "restarted": restarted,
                "resumed": resumed,
            },
        )
        if tool_coverage["complete"] and player_action_completed and resumed:
            break

    fresh_recovery: dict[str, Any] = {}
    if not tool_coverage["complete"]:
        try:
            fresh_recovery = _fresh_tool_recovery(
                owner, campaign_id, unit, list(tool_coverage["gaps"])
            )
        except (ApiFailure, httpx.HTTPError) as exc:
            fresh_recovery = {"error": f"{type(exc).__name__}: {exc}"}
        calls = _calls(args.tool_audit, campaign_id, args.service_repo)
        tool_coverage = _tool_coverage(unit, calls)

    maximum_sequence = max(
        [int(item.get("sequence") or 0) for item in player_snapshot.get("messages") or []],
        default=0,
    )
    player.request(
        "PUT",
        f"/api/campaigns/{campaign_id}/room/read",
        expected=200,
        json_body={"last_read_sequence": maximum_sequence},
    )
    cursor = int(owner_snapshot.get("event_cursor") or 0)
    events = _events_through(owner, campaign_id, cursor) if cursor else []
    _write_json(unit_dir / "room-events.json", events)
    usage = list(owner.request("GET", "/api/usage/ledger", expected=200))
    usage = [item for item in usage if item.get("campaign_id") == campaign_id]
    _write_json(unit_dir / "usage.json", usage)
    service_coverage = _service_checks(
        owner_user=owner_user,
        player_user=player_user,
        members=members,
        owner_snapshot=owner_snapshot,
        player_snapshot=player_snapshot,
        events=events,
        idempotent_replay=idempotent_replay,
        player_action_completed=player_action_completed,
        usage=usage,
        restarted=restarted or args.skip_restart,
        resumed=resumed or args.skip_restart,
    )
    report = {
        "schema": "sagasmith.contentlib-service-chain-regression.v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "model": MODEL,
        "base_url": args.base_url,
        "unit": unit,
        "campaign_id": campaign_id,
        "account_ids": {"owner": owner_user["id"], "player": player_user["id"]},
        "cycles": cycles,
        "idempotent_replay": idempotent_replay,
        "player_action_completed": player_action_completed,
        "fresh_tool_recovery": fresh_recovery,
        "restart": _read_json(unit_dir / "restart.json")
        if (unit_dir / "restart.json").is_file()
        else {},
        "resume_probe": _read_json(unit_dir / "resume-probe.json")
        if (unit_dir / "resume-probe.json").is_file()
        else {},
        "service_coverage": service_coverage,
        "tool_coverage": tool_coverage,
        "complete": service_coverage["complete"] and tool_coverage["complete"],
        "gaps": [
            *[f"service:{item}" for item in service_coverage["gaps"]],
            *[f"tool:{item}" for item in tool_coverage["gaps"]],
        ],
        "artifacts": {
            "http_log": str(owner.log_path.resolve()),
            "room_events": str((unit_dir / "room-events.json").resolve()),
            "usage": str((unit_dir / "usage.json").resolve()),
            "tool_audit": str(args.tool_audit.resolve()),
        },
    }
    _write_json(report_path, report)
    return report


def _summary(
    selected: set[str], reports: list[dict[str, Any]], parallelism: int
) -> dict[str, Any]:
    ordered_reports = sorted(reports, key=lambda item: str(item["unit"]["id"]))
    return {
        "schema": "sagasmith.contentlib-service-chain-regression-summary.v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "model": MODEL,
        "parallelism": parallelism,
        "selected": sorted(selected),
        "complete": len(reports) == len(selected)
        and all(item["complete"] for item in reports),
        "campaigns": [
            {
                "id": item["unit"]["id"],
                "system_id": item["unit"]["system_id"],
                "logical_campaign_line": item["unit"]["logical_campaign_line"],
                "campaign_id": item["campaign_id"],
                "complete": item["complete"],
                "gaps": item["gaps"],
                "tool_calls": item["tool_coverage"]["tool_calls"],
            }
            for item in ordered_reports
        ],
    }


RUNNER_EXCEPTIONS = (
    AttributeError,
    httpx.HTTPError,
    KeyError,
    OSError,
    RuntimeError,
    subprocess.SubprocessError,
    TypeError,
    ValueError,
)


def _error_report(
    args: argparse.Namespace, unit: dict[str, Any], exc: BaseException
) -> dict[str, Any]:
    unit_dir = args.output_dir / "campaigns" / _safe_id(unit["id"])
    unit_dir.mkdir(parents=True, exist_ok=True)
    error = {
        "at": datetime.now(UTC).isoformat(),
        "type": type(exc).__name__,
        "message": str(exc),
    }
    error_path = unit_dir / "runner-error.json"
    _write_json(error_path, error)
    report = {
        "schema": "sagasmith.contentlib-service-chain-regression.v2",
        "generated_at": error["at"],
        "model": MODEL,
        "base_url": args.base_url,
        "unit": unit,
        "campaign_id": "",
        "service_coverage": {"complete": False, "checks": {}, "gaps": []},
        "tool_coverage": {
            "complete": False,
            "checks": {},
            "gaps": [],
            "tool_calls": 0,
        },
        "complete": False,
        "gaps": [f"runner:{type(exc).__name__}:{exc}"],
        "artifacts": {"runner_error": str(error_path.resolve())},
    }
    _write_json(unit_dir / "campaign-report.json", report)
    return report


def _run_isolated_unit(
    args: argparse.Namespace,
    unit: dict[str, Any],
    owner_user: dict[str, Any],
    player_user: dict[str, Any],
    owner_cookies: dict[str, str],
    player_cookies: dict[str, str],
) -> dict[str, Any]:
    unit_dir = args.output_dir / "campaigns" / _safe_id(unit["id"])
    http_log = unit_dir / "service-http.jsonl"
    owner = ServiceClient(
        args.base_url, args.timeout_seconds, http_log, f"owner:{unit['id']}"
    )
    player = ServiceClient(
        args.base_url, args.timeout_seconds, http_log, f"player:{unit['id']}"
    )
    try:
        owner.client.cookies.update(owner_cookies)
        player.client.cookies.update(player_cookies)
        return _run_unit(args, unit, owner, player, owner_user, player_user)
    except RUNNER_EXCEPTIONS as exc:
        return _error_report(args, unit, exc)
    finally:
        owner.close()
        player.close()


def _run(args: argparse.Namespace) -> int:
    if args.max_cycles < 2:
        raise ValueError("--max-cycles must be at least 2 for restart/resume evidence")
    if args.parallelism < 1:
        raise ValueError("--parallelism must be at least 1")
    if args.parallelism > 1 and not args.skip_restart:
        raise ValueError("parallel campaigns require --skip-restart")
    if args.parallelism > 1 and args.fail_fast:
        raise ValueError("--fail-fast cannot be combined with parallel campaigns")
    if args.output_dir.exists() and any(args.output_dir.iterdir()) and not args.resume:
        raise ValueError("--output-dir is not empty; use --resume or a fresh directory")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    inventory = _inventory()
    selected = set(args.campaign or [item["id"] for item in inventory])
    known = {item["id"] for item in inventory}
    unknown = sorted(selected - known)
    if unknown:
        raise ValueError(f"unknown current module Pack ids: {unknown}")
    _write_json(
        args.output_dir / "inventory.json",
        {
            "schema": "sagasmith.current-campaign-service-regression-inventory.v2",
            "generated_at": datetime.now(UTC).isoformat(),
            "model": MODEL,
            "parallelism": args.parallelism,
            "modules": inventory,
            "selected": sorted(selected),
            "explicit_exclusions": [
                {"id": item["id"], "reason": "not selected by --campaign"}
                for item in inventory
                if item["id"] not in selected
            ],
        },
    )
    if args.inventory_only:
        return 0

    _refresh_runtime(args)

    credentials_path = args.output_dir / "accounts.json"
    if args.resume and credentials_path.is_file():
        credentials = _read_json(credentials_path)
    else:
        run_id = uuid.uuid4().hex[:12]
        password = f"Sg!{secrets.token_urlsafe(24)}"
        credentials = {
            "owner": {
                "email": f"contentlib-owner-{run_id}@example.com",
                "password": password,
                "display_name": "Contentlib DM",
            },
            "player": {
                "email": f"contentlib-player-{run_id}@example.com",
                "password": password,
                "display_name": "Contentlib Player",
            },
        }
        _write_json(credentials_path, credentials)

    http_log = args.output_dir / "service-http.jsonl"
    owner = ServiceClient(args.base_url, args.timeout_seconds, http_log, "owner")
    player = ServiceClient(args.base_url, args.timeout_seconds, http_log, "player")
    reports: list[dict[str, Any]] = []
    try:
        _wait_ready(owner)
        owner_user, owner_auth = _register_or_login(owner, dict(credentials["owner"]))
        player_user, player_auth = _register_or_login(player, dict(credentials["player"]))
        _write_json(
            args.output_dir / "accounts-public.json",
            {
                "owner": {"user": owner_user, "auth": owner_auth},
                "player": {"user": player_user, "auth": player_auth},
            },
        )
        owner_cookies = dict(owner.client.cookies.items())
        player_cookies = dict(player.client.cookies.items())
        units = [unit for unit in inventory if unit["id"] in selected]
        if args.parallelism == 1:
            for unit in units:
                report = _run_isolated_unit(
                    args,
                    unit,
                    owner_user,
                    player_user,
                    owner_cookies,
                    player_cookies,
                )
                reports.append(report)
                _write_json(
                    args.output_dir / "summary.json",
                    _summary(selected, reports, args.parallelism),
                )
                if args.fail_fast and not report["complete"]:
                    break
        else:
            with ThreadPoolExecutor(
                max_workers=min(args.parallelism, len(units)),
                thread_name_prefix="campaign-regression",
            ) as executor:
                futures = {
                    executor.submit(
                        _run_isolated_unit,
                        args,
                        unit,
                        owner_user,
                        player_user,
                        owner_cookies,
                        player_cookies,
                    ): unit
                    for unit in units
                }
                for future in as_completed(futures):
                    reports.append(future.result())
                    _write_json(
                        args.output_dir / "summary.json",
                        _summary(selected, reports, args.parallelism),
                    )
    finally:
        owner.close()
        player.close()
    return (
        0
        if len(reports) == len(selected) and all(item["complete"] for item in reports)
        else 1
    )


def main() -> None:
    raise SystemExit(_run(_arguments()))


if __name__ == "__main__":
    main()
