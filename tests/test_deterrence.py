from datetime import datetime, timedelta
from pathlib import Path
import tempfile

from src.config import DeterrenceConfig
from src.deterrence import ActuatorResult, DeterrenceController, build_audible_waveform
from src.storage import Storage


class FakeActuator:
    def __init__(self, mode, success=True, error=None):
        self.mode = mode
        self.success = success
        self.error = error
        self.calls = 0

    def fire(self, config):
        self.calls += 1
        return ActuatorResult(self.mode, self.success, self.error)


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


def make_controller(config, clock=None, audible=None, ultrasonic=None):
    tmpdir = tempfile.TemporaryDirectory()
    storage = Storage(Path(tmpdir.name))
    controller = DeterrenceController(
        config,
        storage,
        audible_actuator=audible or FakeActuator("audible"),
        ultrasonic_actuator=ultrasonic or FakeActuator("ultrasonic"),
        now_func=clock or datetime.now,
    )
    controller._tmpdir = tmpdir
    return controller


def test_manual_fire_logs_enabled_modes():
    config = DeterrenceConfig(audible_enabled=True, ultrasonic_enabled=True)
    controller = make_controller(config)

    events = controller.manual_fire(["both"])

    assert [event.mode for event in events] == ["audible", "ultrasonic"]
    assert all(event.status == "fired" for event in events)
    assert len(controller.storage.list_deterrence_events()) == 2


def test_manual_fire_rejects_disabled_mode():
    controller = make_controller(DeterrenceConfig(audible_enabled=False))

    events = controller.manual_fire(["audible"])

    assert events[0].status == "failed"
    assert "disabled" in events[0].error


def test_auto_fire_respects_threshold_cooldown_and_incident_limit():
    clock = FakeClock(datetime(2026, 1, 1, 12, 0, 0))
    audible = FakeActuator("audible")
    controller = make_controller(
        DeterrenceConfig(
            audible_enabled=True,
            auto_enabled=True,
            bark_score_threshold=0.5,
            cooldown_sec=5,
            max_fires_per_incident=1,
        ),
        clock=clock,
        audible=audible,
    )

    assert controller.handle_bark_detection(score=0.2, audio_level=0.3) == []
    fired = controller.handle_bark_detection(score=0.8, audio_level=0.3)
    assert len(fired) == 1
    assert audible.calls == 1
    assert controller.handle_bark_detection(score=0.9, audio_level=0.3) == []

    clock.advance(10)
    assert controller.handle_bark_detection(score=0.9, audio_level=0.3) == []
    controller.reset_incident()
    assert len(controller.handle_bark_detection(score=0.9, audio_level=0.3)) == 1


def test_auto_fire_respects_quiet_hours():
    clock = FakeClock(datetime(2026, 1, 1, 23, 0, 0))
    controller = make_controller(
        DeterrenceConfig(
            audible_enabled=True,
            auto_enabled=True,
            quiet_hours_enabled=True,
            quiet_hours_start="22:00",
            quiet_hours_end="07:00",
        ),
        clock=clock,
    )

    assert controller.handle_bark_detection(score=0.9, audio_level=0.3) == []


def test_audible_waveform_is_bounded_float_audio():
    waveform = build_audible_waveform("chirp", duration_sec=0.25, sample_rate=16000)

    assert waveform.dtype.name == "float32"
    assert waveform.shape == (4000,)
    assert waveform.max() <= 0.61
    assert waveform.min() >= -0.61
