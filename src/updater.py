"""Headless software update checks and release application."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from src.config import get_data_dir

STATE_FILENAME = "update-state.json"
REQUEST_FILENAME = "update-request.json"
LOCK_FILENAME = "update.lock"
LOG_LIMIT = 120
DEFAULT_HEALTH_URL = "http://127.0.0.1:8080/health"
DEFAULT_HEALTH_TIMEOUT_SEC = 90.0
DEFAULT_HEALTH_INTERVAL_SEC = 1.0


class UpdateError(RuntimeError):
    """Raised when an update command cannot complete."""


def read_update_status(
    project_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Return persisted update state plus current local Git version."""
    project_dir = _project_dir(project_dir)
    data_dir = _data_dir(data_dir)
    state = _read_json(_state_path(data_dir), {})
    pending = read_pending_request(data_dir)

    state.update({
        "current_version": _git_value(["git", "describe", "--tags", "--always", "--dirty"], project_dir),
        "current_ref": _current_ref(project_dir),
        "current_commit": _git_value(["git", "rev-parse", "--short", "HEAD"], project_dir),
        "pending_request": pending,
    })
    state["update_available"] = bool(
        state.get("latest_version")
        and state.get("current_version")
        and not str(state["current_version"]).startswith(str(state["latest_version"]))
    )
    if pending and state.get("state") not in {"updating", "failed"}:
        state["state"] = "pending"
    else:
        state.setdefault("state", "idle")
    state.setdefault("logs", [])
    return state


def check_for_updates(
    project_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    *,
    fetch: bool = True,
    runner: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
) -> dict[str, Any]:
    """Fetch release tags and persist the latest available version."""
    project_dir = _project_dir(project_dir)
    data_dir = _data_dir(data_dir)
    _ensure_data_dir(data_dir)
    _merge_state(data_dir, {"state": "checking", "last_check_started_at": _utc_now()})
    append_log(data_dir, "Checking origin for release tags")

    try:
        if fetch:
            _run(["git", "fetch", "--tags", "--force", "origin"], project_dir, data_dir, runner=runner, timeout=120)
        tags = _git_lines(["git", "tag", "--list", "v*"], project_dir, runner=runner)
        latest = select_latest_tag(tags)
        status = {
            "state": "idle",
            "latest_version": latest,
            "last_checked_at": _utc_now(),
            "last_error": None,
        }
        _merge_state(data_dir, status)
        append_log(data_dir, f"Latest release tag: {latest or 'none found'}")
        return read_update_status(project_dir, data_dir)
    except Exception as exc:
        _merge_state(data_dir, {
            "state": "failed",
            "last_checked_at": _utc_now(),
            "last_error": str(exc),
        })
        append_log(data_dir, f"Update check failed: {exc}")
        raise


def queue_update_request(
    target: str = "latest",
    project_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Persist a request for the updater service to apply."""
    project_dir = _project_dir(project_dir)
    data_dir = _data_dir(data_dir)
    _ensure_data_dir(data_dir)
    clean_target = (target or "latest").strip() or "latest"
    request = {
        "target": clean_target,
        "requested_at": _utc_now(),
    }
    _write_json_atomic(_request_path(data_dir), request)
    _merge_state(data_dir, {
        "state": "pending",
        "requested_target": clean_target,
        "requested_at": request["requested_at"],
        "last_error": None,
    })
    append_log(data_dir, f"Queued update request for {clean_target}")
    return read_update_status(project_dir, data_dir)


def read_pending_request(data_dir: Optional[Path] = None) -> Optional[dict[str, Any]]:
    request = _read_json(_request_path(_data_dir(data_dir)), None)
    return request if isinstance(request, dict) else None


def trigger_update_service(
    service_name: str = "doggy-detector-updater.service",
    *,
    runner: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
) -> dict[str, Any]:
    """Ask systemd to start the updater service.

    On an installed Pi this is authorized through a narrow sudoers rule created
    by scripts/install.sh. Local development machines may not have that rule.
    """
    systemctl = shutil.which("systemctl") or "/bin/systemctl"
    command = [systemctl, "start", service_name]
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        command = ["sudo", "-n", *command]

    try:
        result = (runner or subprocess.run)(
            command,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as exc:
        return {"triggered": False, "error": str(exc)}

    output = _combined_output(result)
    return {
        "triggered": result.returncode == 0,
        "error": None if result.returncode == 0 else output or f"exit {result.returncode}",
    }


def apply_pending_update(
    project_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    *,
    runner: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
    health_check: Optional[Callable[[], tuple[bool, str]]] = None,
    health_timeout_sec: float = DEFAULT_HEALTH_TIMEOUT_SEC,
    health_interval_sec: float = DEFAULT_HEALTH_INTERVAL_SEC,
) -> dict[str, Any]:
    """Apply the queued release update, restart the detector, and persist status."""
    project_dir = _project_dir(project_dir)
    data_dir = _data_dir(data_dir)
    _ensure_data_dir(data_dir)
    pending = read_pending_request(data_dir)
    if not pending:
        append_log(data_dir, "Updater started with no pending request")
        return read_update_status(project_dir, data_dir)

    lock_path = _lock_path(data_dir)
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        _merge_state(data_dir, {"state": "updating", "last_error": "update already running"})
        return read_update_status(project_dir, data_dir)

    previous_ref = _current_ref(project_dir)
    target = str(pending.get("target") or "latest")
    resolved_target = target
    started_at = _utc_now()
    os.close(lock_fd)

    try:
        _merge_state(data_dir, {
            "state": "updating",
            "requested_target": target,
            "resolved_target": None,
            "previous_ref": previous_ref,
            "last_update_started_at": started_at,
            "last_error": None,
        })
        append_log(data_dir, f"Starting update from {previous_ref} to {target}")
        _ensure_clean_worktree(project_dir, data_dir, runner=runner)
        _run(["git", "fetch", "--tags", "--force", "origin"], project_dir, data_dir, runner=runner, timeout=120)

        if target == "latest":
            latest = select_latest_tag(_git_lines(["git", "tag", "--list", "v*"], project_dir, runner=runner))
            if not latest:
                raise UpdateError("No release tags found")
            resolved_target = latest
        else:
            _ensure_tag_exists(project_dir, target, runner=runner)

        _merge_state(data_dir, {"resolved_target": resolved_target})
        _run(["git", "checkout", resolved_target], project_dir, data_dir, runner=runner, timeout=120)
        _install_dependencies(project_dir, data_dir, runner=runner)
        restarted = _restart_detector(data_dir, runner=runner)
        if restarted:
            _wait_for_detector_health(
                data_dir,
                health_check=health_check,
                timeout_sec=health_timeout_sec,
                interval_sec=health_interval_sec,
            )

        _request_path(data_dir).unlink(missing_ok=True)
        _merge_state(data_dir, {
            "state": "succeeded",
            "current_version": _git_value(["git", "describe", "--tags", "--always", "--dirty"], project_dir, runner=runner),
            "latest_version": resolved_target,
            "last_update_completed_at": _utc_now(),
            "last_error": None,
        })
        append_log(data_dir, f"Update applied successfully: {resolved_target}")
        return read_update_status(project_dir, data_dir)
    except Exception as exc:
        append_log(data_dir, f"Update failed: {exc}")
        rolled_back = _attempt_rollback(project_dir, data_dir, previous_ref, runner=runner)
        _merge_state(data_dir, {
            "state": "failed",
            "last_update_completed_at": _utc_now(),
            "last_error": str(exc),
            "rolled_back": rolled_back,
        })
        raise
    finally:
        lock_path.unlink(missing_ok=True)


def append_log(data_dir: Path, message: str) -> None:
    state = _read_json(_state_path(data_dir), {})
    logs = state.get("logs", [])
    if not isinstance(logs, list):
        logs = []
    logs.append({"at": _utc_now(), "message": message})
    state["logs"] = logs[-LOG_LIMIT:]
    _write_json_atomic(_state_path(data_dir), state)


def select_latest_tag(tags: Iterable[str]) -> Optional[str]:
    clean_tags = [tag.strip() for tag in tags if tag and tag.strip()]
    if not clean_tags:
        return None
    return sorted(clean_tags, key=_version_sort_key)[-1]


def _install_dependencies(
    project_dir: Path,
    data_dir: Path,
    *,
    runner: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
) -> None:
    command = [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]
    _run(command, project_dir, data_dir, runner=runner, timeout=600)


def _restart_detector(
    data_dir: Path,
    *,
    runner: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
) -> bool:
    if _env_truthy("DOG_DETECTOR_SKIP_SERVICE_RESTART"):
        append_log(data_dir, "Skipping service restart because DOG_DETECTOR_SKIP_SERVICE_RESTART is set")
        return False

    systemctl = shutil.which("systemctl") or "/bin/systemctl"
    command = [systemctl, "restart", "doggy-detector"]
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        command = ["sudo", "-n", *command]
    _run(command, Path.cwd(), data_dir, runner=runner, timeout=60)
    return True


def _wait_for_detector_health(
    data_dir: Path,
    *,
    health_check: Optional[Callable[[], tuple[bool, str]]] = None,
    timeout_sec: float = DEFAULT_HEALTH_TIMEOUT_SEC,
    interval_sec: float = DEFAULT_HEALTH_INTERVAL_SEC,
) -> None:
    if _env_truthy("DOG_DETECTOR_SKIP_HEALTH_CHECK"):
        append_log(data_dir, "Skipping post-restart health check because DOG_DETECTOR_SKIP_HEALTH_CHECK is set")
        return

    deadline = time.monotonic() + max(0.0, timeout_sec)
    last_detail = "not checked"
    while True:
        ok, detail = (health_check or _http_detector_health)()
        if ok:
            append_log(data_dir, f"Detector health check passed: {detail}")
            return
        last_detail = detail
        if time.monotonic() >= deadline:
            break
        sleep_for = min(max(0.0, interval_sec), max(0.0, deadline - time.monotonic()))
        if sleep_for > 0:
            time.sleep(sleep_for)

    raise UpdateError(f"Detector health check failed after restart: {last_detail}")


def _http_detector_health() -> tuple[bool, str]:
    health_url = os.environ.get("DOG_DETECTOR_HEALTH_URL", DEFAULT_HEALTH_URL)
    try:
        with urllib.request.urlopen(health_url, timeout=3) as response:
            status_code = response.getcode()
            if 200 <= status_code < 300:
                return True, f"HTTP {status_code}"
            return False, f"HTTP {status_code}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:
        return False, str(exc)


def _attempt_rollback(
    project_dir: Path,
    data_dir: Path,
    previous_ref: str,
    *,
    runner: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
) -> bool:
    if not previous_ref or previous_ref == "unknown":
        append_log(data_dir, "Rollback skipped because previous ref is unknown")
        return False
    try:
        append_log(data_dir, f"Rolling back to {previous_ref}")
        _run(["git", "checkout", previous_ref], project_dir, data_dir, runner=runner, timeout=120)
        _install_dependencies(project_dir, data_dir, runner=runner)
        _restart_detector(data_dir, runner=runner)
        append_log(data_dir, f"Rollback completed: {previous_ref}")
        return True
    except Exception as exc:
        append_log(data_dir, f"Rollback failed: {exc}")
        return False


def _ensure_clean_worktree(
    project_dir: Path,
    data_dir: Path,
    *,
    runner: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
) -> None:
    result = _git_value(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        project_dir,
        runner=runner,
    )
    if result.strip():
        append_log(data_dir, "Refusing update because tracked files are modified")
        raise UpdateError("Tracked files are modified; commit or reset local changes before updating")


def _ensure_tag_exists(
    project_dir: Path,
    tag: str,
    *,
    runner: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
) -> None:
    tags = set(_git_lines(["git", "tag", "--list", tag], project_dir, runner=runner))
    if tag not in tags:
        raise UpdateError(f"Release tag not found: {tag}")


def _current_ref(project_dir: Path) -> str:
    branch = _git_value(["git", "branch", "--show-current"], project_dir)
    if branch:
        return branch
    tag = _git_value(["git", "describe", "--tags", "--exact-match"], project_dir)
    if tag:
        return tag
    return _git_value(["git", "rev-parse", "--short", "HEAD"], project_dir) or "unknown"


def _git_value(
    command: list[str],
    cwd: Path,
    *,
    runner: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
) -> str:
    try:
        result = (runner or subprocess.run)(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip()


def _git_lines(
    command: list[str],
    cwd: Path,
    *,
    runner: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
) -> list[str]:
    value = _git_value(command, cwd, runner=runner)
    return [] if value in {"", "unknown"} else value.splitlines()


def _run(
    command: list[str],
    cwd: Path,
    data_dir: Path,
    *,
    runner: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    append_log(data_dir, f"Running: {' '.join(command)}")
    result = (runner or subprocess.run)(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = _combined_output(result)
    if output:
        for line in output.splitlines()[-20:]:
            append_log(data_dir, line)
    if result.returncode != 0:
        raise UpdateError(output or f"Command failed with exit code {result.returncode}")
    return result


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part).strip()


def _merge_state(data_dir: Path, values: dict[str, Any]) -> None:
    state = _read_json(_state_path(data_dir), {})
    logs = state.get("logs", [])
    state.update(values)
    if "logs" not in values:
        state["logs"] = logs if isinstance(logs, list) else []
    _write_json_atomic(_state_path(data_dir), state)


def _read_json(path: Path, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp_path.replace(path)


def _version_sort_key(tag: str) -> tuple[Any, ...]:
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$", tag)
    if match:
        return (1, int(match.group(1)), int(match.group(2)), int(match.group(3)), tag)
    return (0, tag)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_path(data_dir: Path) -> Path:
    return data_dir / STATE_FILENAME


def _request_path(data_dir: Path) -> Path:
    return data_dir / REQUEST_FILENAME


def _lock_path(data_dir: Path) -> Path:
    return data_dir / LOCK_FILENAME


def _project_dir(project_dir: Optional[Path]) -> Path:
    return Path(project_dir) if project_dir is not None else Path.cwd()


def _data_dir(data_dir: Optional[Path]) -> Path:
    return Path(data_dir) if data_dir is not None else get_data_dir()


def _ensure_data_dir(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Doggy Detector updater")
    parser.add_argument("--project-dir", type=Path, default=Path.cwd())
    parser.add_argument("--data-dir", type=Path, default=get_data_dir())
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status")
    subparsers.add_parser("check")
    request_parser = subparsers.add_parser("request")
    request_parser.add_argument("target", nargs="?", default="latest")
    subparsers.add_parser("apply-pending")

    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            payload = read_update_status(args.project_dir, args.data_dir)
        elif args.command == "check":
            payload = check_for_updates(args.project_dir, args.data_dir)
        elif args.command == "request":
            payload = queue_update_request(args.target, args.project_dir, args.data_dir)
        elif args.command == "apply-pending":
            payload = apply_pending_update(args.project_dir, args.data_dir)
        else:
            parser.error(f"Unknown command: {args.command}")
            return 2
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
