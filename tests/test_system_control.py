import src.system_control as system_control


class FakeProcess:
    pid = 4321


def test_queue_detector_restart_requires_systemctl(monkeypatch):
    monkeypatch.setattr(system_control.shutil, "which", lambda name: None)

    result = system_control.queue_detector_restart()

    assert result["queued"] is False
    assert result["error"] == "systemctl is not available on this machine"


def test_queue_detector_restart_detaches_exact_systemd_command(monkeypatch):
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(system_control.shutil, "which", lambda name: "/usr/bin/systemctl")
    monkeypatch.setattr(system_control.os, "geteuid", lambda: 1000)

    result = system_control.queue_detector_restart(delay_sec=0.25, popen=fake_popen)

    assert result["queued"] is True
    assert result["pid"] == 4321
    assert captured["command"][:2] == [system_control.sys.executable, "-c"]
    assert "time.sleep(0.25)" in captured["command"][2]
    assert "['sudo', '-n', '/usr/bin/systemctl', 'restart', 'doggy-detector']" in captured["command"][2]
    assert captured["kwargs"]["stdin"] is system_control.subprocess.DEVNULL
    assert captured["kwargs"]["stdout"] is system_control.subprocess.DEVNULL
    assert captured["kwargs"]["stderr"] is system_control.subprocess.DEVNULL
    assert captured["kwargs"]["start_new_session"] is True
    assert captured["kwargs"]["close_fds"] is True
