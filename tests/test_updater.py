import json
import subprocess

import pytest

from src.updater import (
    UpdateError,
    apply_pending_update,
    check_for_updates,
    queue_update_request,
    read_pending_request,
    select_latest_tag,
)


def test_select_latest_tag_prefers_semver_order():
    assert select_latest_tag(["v0.1.0", "v0.10.0", "v0.2.0"]) == "v0.10.0"


def test_queue_update_request_persists_pending_status(tmp_path):
    project_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    project_dir.mkdir()

    status = queue_update_request("v1.2.3", project_dir=project_dir, data_dir=data_dir)

    assert status["state"] == "pending"
    assert status["pending_request"]["target"] == "v1.2.3"
    assert read_pending_request(data_dir)["target"] == "v1.2.3"


def test_check_for_updates_reads_local_tags_without_network(tmp_path):
    project_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    project_dir.mkdir()
    _git(["init"], project_dir)
    _git(["config", "user.email", "test@example.com"], project_dir)
    _git(["config", "user.name", "Test User"], project_dir)
    (project_dir / "README.md").write_text("test\n", encoding="utf-8")
    _git(["add", "README.md"], project_dir)
    _git(["commit", "-m", "init"], project_dir)
    _git(["tag", "v0.1.0"], project_dir)
    _git(["tag", "v0.3.0"], project_dir)
    _git(["tag", "v0.2.0"], project_dir)

    status = check_for_updates(project_dir=project_dir, data_dir=data_dir, fetch=False)

    assert status["latest_version"] == "v0.3.0"
    assert status["state"] == "idle"
    assert status["last_error"] is None


def test_apply_pending_update_waits_for_detector_health(tmp_path):
    project_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _init_repo(project_dir)
    queue_update_request("v0.2.0", project_dir=project_dir, data_dir=data_dir)

    status = apply_pending_update(
        project_dir=project_dir,
        data_dir=data_dir,
        runner=_fake_update_runner,
        health_check=lambda: (True, "ok"),
        health_timeout_sec=0,
        health_interval_sec=0,
    )

    assert status["state"] == "succeeded"
    assert status["latest_version"] == "v0.2.0"
    assert read_pending_request(data_dir) is None


def test_apply_pending_update_fails_when_detector_health_never_recovers(tmp_path):
    project_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _init_repo(project_dir)
    queue_update_request("v0.2.0", project_dir=project_dir, data_dir=data_dir)

    with pytest.raises(UpdateError):
        apply_pending_update(
            project_dir=project_dir,
            data_dir=data_dir,
            runner=_fake_update_runner,
            health_check=lambda: (False, "connection refused"),
            health_timeout_sec=0,
            health_interval_sec=0,
        )

    state = json.loads((data_dir / "update-state.json").read_text())
    assert state["state"] == "failed"
    assert "Detector health check failed" in state["last_error"]
    assert read_pending_request(data_dir)["target"] == "v0.2.0"


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(project_dir):
    project_dir.mkdir()
    _git(["init"], project_dir)
    _git(["config", "user.email", "test@example.com"], project_dir)
    _git(["config", "user.name", "Test User"], project_dir)
    (project_dir / "README.md").write_text("test\n", encoding="utf-8")
    _git(["add", "README.md"], project_dir)
    _git(["commit", "-m", "init"], project_dir)


def _fake_update_runner(command, **kwargs):
    if command[:3] == ["git", "tag", "--list"]:
        return subprocess.CompletedProcess(command, 0, "v0.2.0\n", "")
    return subprocess.CompletedProcess(command, 0, "", "")
