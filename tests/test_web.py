import pytest
from pathlib import Path
from datetime import datetime
import subprocess
import tempfile
import zipfile
import io

from fastapi.testclient import TestClient

from src.web.app import create_app
from src.config import Config, SettingsStore
from src.deterrence import ActuatorResult
from src.storage import Storage, Event


@pytest.fixture
def temp_storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Storage(Path(tmpdir))


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def client(config, temp_storage):
    settings_store = SettingsStore(temp_storage.data_dir)
    settings_store.ensure_auth_credentials(username="admin", password="secret")
    app = create_app(config, temp_storage, settings_store)
    app.state.test_username = "admin"
    app.state.test_password = "secret"
    return TestClient(app)


@pytest.fixture
def auth_client(client):
    response = client.post(
        "/api/auth/login",
        json={
            "username": client.app.state.test_username,
            "password": client.app.state.test_password,
        },
    )
    assert response.status_code == 200
    return client


def test_private_routes_require_auth(client):
    response = client.get("/api/events")
    assert response.status_code == 401


def test_health_and_login_routes_are_public(client):
    assert client.get("/login").status_code == 200
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["state"] == "unknown"


def test_valid_login_cookie_grants_access(client):
    login_response = client.post(
        "/api/auth/login",
        json={"username": client.app.state.test_username, "password": client.app.state.test_password},
    )
    assert login_response.status_code == 200

    response = client.get("/api/events")
    assert response.status_code == 200


def test_invalid_login_rejects(client):
    login_response = client.post(
        "/api/auth/login",
        json={"username": client.app.state.test_username, "password": "wrong"},
    )
    assert login_response.status_code == 401


def test_settings_page_requires_auth(client):
    assert client.get("/settings").status_code == 401
    login_response = client.post(
        "/api/auth/login",
        json={"username": client.app.state.test_username, "password": client.app.state.test_password},
    )
    assert login_response.status_code == 200
    response = client.get("/settings")
    assert response.status_code == 200
    assert "Incident Timing" in response.text
    assert "Diagnostics" in response.text
    assert "/static/settings.js?v=" in response.text


def test_logs_page_requires_auth(client):
    assert client.get("/logs").status_code == 401
    login_response = client.post(
        "/api/auth/login",
        json={"username": client.app.state.test_username, "password": client.app.state.test_password},
    )
    assert login_response.status_code == 200

    response = client.get("/logs")
    assert response.status_code == 200
    assert "Logs" in response.text
    assert "logCopyBtn" in response.text
    assert "/static/logs.js?v=" in response.text


def test_dashboard_shows_compact_ops_not_full_health_panel(auth_client):
    response = auth_client.get("/")

    assert response.status_code == 200
    assert "opsStrip" in response.text
    assert "healthChecks" not in response.text
    assert "/static/app.js?v=" in response.text
    assert 'href="/logs"' in response.text


def test_logs_api_reads_whitelisted_journal(auth_client, monkeypatch):
    def fake_run(command, capture_output, text, timeout):
        assert command == [
            "journalctl",
            "-u",
            "doggy-detector",
            "-n",
            "50",
            "--no-pager",
            "-o",
            "short-iso",
        ]
        return subprocess.CompletedProcess(command, 0, stdout="line one\nline two\n", stderr="")

    monkeypatch.setattr("src.web.routes.subprocess.run", fake_run)

    response = auth_client.get("/api/logs?service=app&lines=50")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["unit"] == "doggy-detector"
    assert data["lines"] == ["line one", "line two"]


def test_logs_api_rejects_unknown_service(auth_client):
    response = auth_client.get("/api/logs?service=bad")

    assert response.status_code == 400


def test_dashboard_export_modal_offers_single_zip_package(auth_client):
    response = auth_client.get("/")

    assert response.status_code == 200
    assert "Export Results" in response.text
    assert "Download ZIP" in response.text
    assert "Download CSV" not in response.text
    assert "Download PDF" not in response.text
    assert "downloadCsvBtn" not in response.text


def test_get_status(auth_client):
    response = auth_client.get("/api/status")
    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert "health" in response.json()
    assert "deterrence" in response.json()


def test_list_events_empty(auth_client):
    response = auth_client.get("/api/events")
    assert response.status_code == 200
    data = response.json()
    assert data["events"] == []
    assert data["total"] == 0
    assert data["total_pages"] == 1


def test_list_events_with_data(auth_client, temp_storage):
    event = Event(
        started_at=datetime(2024, 1, 15, 10, 0, 0),
        ended_at=datetime(2024, 1, 15, 10, 0, 5),
        duration_sec=5.0,
        bark_count=3,
        peak_score=0.8,
        avg_score=0.7,
        detection_threshold=0.12,
        peak_audio_level=0.34,
        avg_audio_level=0.22,
        direction="center",
        clip_path="clips/2024-01-15/10-00-00_000.wav",
    )
    temp_storage.save_event(event)

    response = auth_client.get("/api/events")
    assert response.status_code == 200
    data = response.json()
    assert len(data["events"]) == 1
    assert data["events"][0]["bark_count"] == 3
    assert data["events"][0]["started_at"] == "2024-01-15T10:00:00"
    assert data["events"][0]["duration_sec"] == 5.0
    assert data["events"][0]["peak_score"] == 0.8
    assert data["events"][0]["avg_score"] == 0.7
    assert data["events"][0]["detection_threshold"] == 0.12
    assert data["events"][0]["peak_audio_level"] == 0.34
    assert data["events"][0]["avg_audio_level"] == 0.22
    assert data["events"][0]["direction"] == "center"
    assert data["events"][0]["clip_url"] == "/api/clips/2024-01-15/10-00-00_000.wav"
    assert "clip_hash" in data["events"][0]


def test_get_event_detail(auth_client, temp_storage):
    event = Event(
        started_at=datetime(2024, 1, 15, 10, 0, 0),
        ended_at=datetime(2024, 1, 15, 10, 0, 5),
        duration_sec=5.0,
        bark_count=3,
        peak_score=0.8,
        avg_score=0.7,
        clip_path="clips/2024-01-15/detail.wav",
        clip_hash="abc123",
        weather_temp_f=72.0,
        weather_wind_mph=3.0,
        weather_conditions="clear",
    )
    event_id = temp_storage.save_event(event)

    response = auth_client.get(f"/api/events/{event_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == event_id
    assert data["clip_hash"] == "abc123"
    assert data["weather_conditions"] == "clear"


def test_flag_event(auth_client, temp_storage):
    event = Event(
        started_at=datetime(2024, 1, 15, 10, 0, 0),
        ended_at=datetime(2024, 1, 15, 10, 0, 5),
        duration_sec=5.0,
        bark_count=3,
        peak_score=0.8,
        avg_score=0.7,
    )
    event_id = temp_storage.save_event(event)

    response = auth_client.post(
        f"/api/events/{event_id}/flag",
        json={"reason": "test"},
    )
    assert response.status_code == 200

    retrieved = temp_storage.get_event(event_id)
    assert retrieved.is_false_pos is True


def test_delete_event(auth_client, temp_storage):
    clip_path = temp_storage.data_dir / "clips" / "2024-01-15" / "delete.wav"
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    clip_path.write_bytes(b"delete")
    event = Event(
        started_at=datetime(2024, 1, 15, 10, 0, 0),
        ended_at=datetime(2024, 1, 15, 10, 0, 5),
        duration_sec=5.0,
        bark_count=3,
        peak_score=0.8,
        avg_score=0.7,
        clip_path="clips/2024-01-15/delete.wav",
    )
    event_id = temp_storage.save_event(event)

    response = auth_client.delete(f"/api/events/{event_id}")

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert temp_storage.get_event(event_id) is None
    assert not clip_path.exists()


def test_delete_event_missing_returns_404(auth_client):
    response = auth_client.delete("/api/events/999")

    assert response.status_code == 404


def test_only_false_positive_filter(auth_client, temp_storage):
    valid = Event(
        started_at=datetime(2024, 1, 15, 10, 0, 0),
        ended_at=datetime(2024, 1, 15, 10, 0, 5),
        duration_sec=5.0,
        bark_count=3,
        peak_score=0.8,
        avg_score=0.7,
    )
    false_pos = Event(
        started_at=datetime(2024, 1, 15, 11, 0, 0),
        ended_at=datetime(2024, 1, 15, 11, 0, 5),
        duration_sec=5.0,
        bark_count=3,
        peak_score=0.8,
        avg_score=0.7,
        is_false_pos=True,
    )
    temp_storage.save_event(valid)
    temp_storage.save_event(false_pos)

    response = auth_client.get("/api/events?only_false_pos=true")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["events"][0]["is_false_pos"] is True


def test_summary_excludes_false_positives(auth_client, temp_storage):
    temp_storage.save_event(Event(
        started_at=datetime.now(),
        ended_at=datetime.now(),
        duration_sec=5.0,
        bark_count=3,
        peak_score=0.8,
        avg_score=0.7,
    ))
    temp_storage.save_event(Event(
        started_at=datetime.now(),
        ended_at=datetime.now(),
        duration_sec=20.0,
        bark_count=5,
        peak_score=0.95,
        avg_score=0.8,
        is_false_pos=True,
    ))

    response = auth_client.get("/api/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["today"]["incident_count"] == 1
    assert data["all_time"]["total_duration_sec"] == 5.0


def test_settings_does_not_leak_auth(auth_client):
    response = auth_client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert "auth" not in data
    assert "token" not in str(data).lower()


class FakeActuator:
    def __init__(self, mode):
        self.mode = mode
        self.calls = 0

    def fire(self, config):
        self.calls += 1
        return ActuatorResult(self.mode, True)


def test_deterrence_settings_and_manual_fire(auth_client):
    controller = auth_client.app.state.deterrence_controller
    controller.audible_actuator = FakeActuator("audible")

    settings_response = auth_client.post("/api/deterrence/settings", json={
        "audible_enabled": True,
        "manual_enabled": True,
        "auto_enabled": True,
        "bark_score_threshold": 0.22,
        "burst_sec": 1.5,
        "cooldown_sec": 3,
    })
    assert settings_response.status_code == 200
    settings = settings_response.json()["deterrence"]
    assert settings["audible_enabled"] is True
    assert settings["auto_enabled"] is True
    assert settings["bark_score_threshold"] == 0.22

    fire_response = auth_client.post("/api/deterrence/fire", json={"modes": ["audible"]})
    assert fire_response.status_code == 200
    assert fire_response.json()["success"] is True
    assert fire_response.json()["events"][0]["mode"] == "audible"

    events_response = auth_client.get("/api/deterrence/events")
    assert events_response.status_code == 200
    assert events_response.json()["events"][0]["status"] == "fired"


def test_deterrence_master_switch_disables_firing(auth_client):
    controller = auth_client.app.state.deterrence_controller
    controller.audible_actuator = FakeActuator("audible")

    settings_response = auth_client.post("/api/deterrence/settings", json={
        "enabled": False,
        "audible_enabled": True,
        "manual_enabled": True,
    })
    assert settings_response.status_code == 200
    assert settings_response.json()["deterrence"]["enabled"] is False

    fire_response = auth_client.post("/api/deterrence/fire", json={"modes": ["audible"]})
    assert fire_response.status_code == 200
    assert fire_response.json()["success"] is False
    assert fire_response.json()["events"][0]["error"] == "deterrence is disabled"

    reenable_response = auth_client.post("/api/deterrence/settings", json={"enabled": True})
    assert reenable_response.status_code == 200
    assert reenable_response.json()["deterrence"]["enabled"] is True


def test_update_status_check_and_request(auth_client, monkeypatch):
    def fake_status(project_dir, data_dir):
        return {
            "state": "idle",
            "current_version": "v0.1.0",
            "latest_version": "v0.2.0",
            "update_available": True,
            "logs": [],
        }

    def fake_check(project_dir, data_dir):
        return {
            "state": "idle",
            "current_version": "v0.1.0",
            "latest_version": "v0.2.0",
            "update_available": True,
            "logs": [{"at": "2026-06-12T00:00:00+00:00", "message": "checked"}],
        }

    def fake_queue(target, project_dir, data_dir):
        return {
            "state": "pending",
            "pending_request": {"target": target},
            "logs": [],
        }

    monkeypatch.setattr("src.web.routes.read_update_status", fake_status)
    monkeypatch.setattr("src.web.routes.check_for_updates", fake_check)
    monkeypatch.setattr("src.web.routes.queue_update_request", fake_queue)
    monkeypatch.setattr(
        "src.web.routes.trigger_update_service",
        lambda: {"triggered": True, "error": None},
    )

    status_response = auth_client.get("/api/update/status")
    assert status_response.status_code == 200
    assert status_response.json()["latest_version"] == "v0.2.0"

    check_response = auth_client.post("/api/update/check")
    assert check_response.status_code == 200
    assert check_response.json()["logs"][0]["message"] == "checked"

    request_response = auth_client.post("/api/update/request", json={"target": "latest"})
    assert request_response.status_code == 200
    data = request_response.json()
    assert data["pending_request"]["target"] == "latest"
    assert data["service_trigger"]["triggered"] is True


def test_update_incident_timing_settings(auth_client):
    response = auth_client.post("/api/settings", json={
        "detection_threshold": 0.083,
        "incidents_min_barks": 3,
        "incidents_gap_sec": 30,
        "incidents_merge_within_sec": 20,
        "incidents_min_duration_sec": 2.5,
        "incidents_pre_roll_sec": 20,
    })

    assert response.status_code == 200
    settings = auth_client.get("/api/settings").json()
    assert settings["detection"]["threshold"] == 0.083
    assert settings["incidents"]["min_barks"] == 3
    assert settings["incidents"]["gap_sec"] == 30.0
    assert settings["incidents"]["merge_within_sec"] == 20.0
    assert settings["incidents"]["min_duration_sec"] == 2.5
    assert settings["incidents"]["pre_roll_sec"] == 20.0
    assert settings["incidents"]["finalize_after_sec"] == 50.0


def test_devices_api_returns_stable_device_keys(auth_client, monkeypatch):
    import src.web.routes

    class FakeSD:
        @staticmethod
        def query_devices():
            return [
                {"name": "Laptop Mic", "max_input_channels": 1, "hostapi": 0},
                {"name": "Mounted Yard Mic", "max_input_channels": 2, "hostapi": 0},
            ]

        @staticmethod
        def query_hostapis(hostapi):
            return {"name": "Core Audio"}

    monkeypatch.setattr(src.web.routes, "sd", FakeSD)

    response = auth_client.get("/api/devices")

    assert response.status_code == 200
    devices = response.json()["devices"]
    assert devices[1]["key"] == "Mounted Yard Mic, Core Audio"
    assert devices[1]["is_stereo"] is True


def test_update_audio_device_saves_pinned_device_key(auth_client):
    response = auth_client.post("/api/settings", json={
        "audio_device": "Mounted Yard Mic, Core Audio",
    })

    assert response.status_code == 200
    settings = auth_client.get("/api/settings").json()
    assert settings["audio"]["device"] == "Mounted Yard Mic, Core Audio"


def test_update_location_accepts_precise_google_coordinates(auth_client):
    response = auth_client.post("/api/settings", json={
        "location_lat": 40.0,
        "location_lon": -105.0,
    })

    assert response.status_code == 200
    settings = auth_client.get("/api/settings").json()
    assert settings["location"]["lat"] == 40.0
    assert settings["location"]["lon"] == -105.0


def test_update_location_rejects_out_of_range_coordinates(auth_client):
    response = auth_client.post("/api/settings", json={
        "location_lat": 100.0,
        "location_lon": -105.0,
    })

    assert response.status_code == 400


def test_report_zip_excludes_false_positive_clips(auth_client, temp_storage, monkeypatch):
    import src.reports

    monkeypatch.setattr(src.reports, "generate_pdf_report", lambda **kwargs: b"%PDF-1.4")

    valid_clip = temp_storage.data_dir / "clips" / "2024-01-15" / "valid.wav"
    false_clip = temp_storage.data_dir / "clips" / "2024-01-15" / "false.wav"
    valid_clip.parent.mkdir(parents=True, exist_ok=True)
    valid_clip.write_bytes(b"valid")
    false_clip.write_bytes(b"false")

    temp_storage.save_event(Event(
        started_at=datetime(2024, 1, 15, 10, 0, 0),
        ended_at=datetime(2024, 1, 15, 10, 0, 5),
        duration_sec=5.0,
        bark_count=3,
        peak_score=0.8,
        avg_score=0.7,
        clip_path="clips/2024-01-15/valid.wav",
        clip_hash="validfullhash1234567890",
    ))
    temp_storage.save_event(Event(
        started_at=datetime(2024, 1, 15, 11, 0, 0),
        ended_at=datetime(2024, 1, 15, 11, 0, 5),
        duration_sec=5.0,
        bark_count=3,
        peak_score=0.8,
        avg_score=0.7,
        clip_path="clips/2024-01-15/false.wav",
        clip_hash="falsefullhash1234567890",
        is_false_pos=True,
    ))

    response = auth_client.get("/api/reports/generate?start_date=2024-01-15&end_date=2024-01-15")
    assert response.status_code == 200

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        names = set(zf.namelist())
        csv_name = next(name for name in names if name.startswith("events_") and name.endswith(".csv"))
        csv_text = zf.read(csv_name).decode()

    assert "clips/2024-01-15/valid.wav" in names
    assert "clips/2024-01-15/false.wav" not in names
    assert csv_name == "events_2024-01-15_to_2024-01-15.csv"
    assert "Clip Hash" in csv_text
    assert "validfullhash1234567890" in csv_text
    assert "falsefullhash1234567890" not in csv_text


def test_csv_export_includes_calibration_fields(auth_client, temp_storage):
    temp_storage.save_event(Event(
        started_at=datetime(2024, 1, 15, 10, 0, 0),
        ended_at=datetime(2024, 1, 15, 10, 0, 5),
        duration_sec=5.0,
        bark_count=3,
        peak_score=0.08,
        avg_score=0.06,
        detection_threshold=0.05,
        peak_audio_level=0.34,
        avg_audio_level=0.22,
        clip_hash="fullcliphashabcdef123456",
    ))

    response = auth_client.get("/api/reports/csv?start_date=2024-01-15&end_date=2024-01-15")

    assert response.status_code == 200
    csv_text = response.text
    assert "Detection Threshold" in csv_text
    assert "Peak Audio Level" in csv_text
    assert "Avg Audio Level" in csv_text
    assert "Clip Hash" in csv_text
    assert "fullcliphashabcdef123456" in csv_text
    assert "0.05" in csv_text
    assert "0.34" in csv_text
    assert "0.22" in csv_text
