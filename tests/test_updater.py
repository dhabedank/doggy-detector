import subprocess

from src.updater import check_for_updates, queue_update_request, read_pending_request, select_latest_tag


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


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
