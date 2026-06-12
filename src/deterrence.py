"""Sonic deterrence controller and actuator backends."""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, time as datetime_time
from typing import Callable, Iterable, Optional

import numpy as np

from src.config import DeterrenceConfig
from src.storage import DeterrenceEvent, Storage

try:
    import sounddevice as sd
except ImportError:
    sd = None

logger = logging.getLogger(__name__)

VALID_MODES = {"audible", "ultrasonic"}


@dataclass
class ActuatorResult:
    mode: str
    success: bool
    error: Optional[str] = None


class AudibleActuator:
    """Play bounded audible deterrent bursts through an output device."""

    sample_rate = 48000

    def fire(self, config: DeterrenceConfig) -> ActuatorResult:
        if sd is None:
            return ActuatorResult("audible", False, "sounddevice is not available")

        duration_sec = _clamp(config.burst_sec, 0.1, 10.0)
        profile = config.audible_profile or "chirp"
        output_device = config.audible_output_device

        def play_burst() -> None:
            try:
                waveform = build_audible_waveform(profile, duration_sec, self.sample_rate)
                sd.play(waveform, self.sample_rate, device=output_device, blocking=True)
            except Exception as exc:
                logger.error("Audible deterrent playback failed: %s", exc)

        threading.Thread(target=play_burst, daemon=True).start()
        return ActuatorResult("audible", True)


class UltrasonicRelayActuator:
    """Pulse an external ultrasonic device through a GPIO-controlled switch."""

    def fire(self, config: DeterrenceConfig) -> ActuatorResult:
        if config.ultrasonic_gpio_pin is None:
            return ActuatorResult("ultrasonic", False, "ultrasonic GPIO pin is not configured")

        try:
            from gpiozero import OutputDevice
        except ImportError:
            return ActuatorResult("ultrasonic", False, "gpiozero is not installed")

        duration_sec = _clamp(config.burst_sec, 0.1, 10.0)
        pin = int(config.ultrasonic_gpio_pin)
        active_high = bool(config.ultrasonic_active_high)

        def pulse() -> None:
            device = None
            try:
                device = OutputDevice(pin, active_high=active_high, initial_value=False)
                device.on()
                time.sleep(duration_sec)
            except Exception as exc:
                logger.error("Ultrasonic deterrent trigger failed: %s", exc)
            finally:
                if device is not None:
                    try:
                        device.off()
                        device.close()
                    except Exception as exc:
                        logger.warning("Could not close ultrasonic GPIO device: %s", exc)

        threading.Thread(target=pulse, daemon=True).start()
        return ActuatorResult("ultrasonic", True)


class DeterrenceController:
    """Apply deterrence policy and log every firing attempt."""

    def __init__(
        self,
        config: DeterrenceConfig,
        storage: Storage,
        audible_actuator: Optional[object] = None,
        ultrasonic_actuator: Optional[object] = None,
        now_func: Callable[[], datetime] = datetime.now,
    ):
        self.config = config
        self.storage = storage
        self.audible_actuator = audible_actuator or AudibleActuator()
        self.ultrasonic_actuator = ultrasonic_actuator or UltrasonicRelayActuator()
        self.now_func = now_func
        self.last_fire_at: Optional[datetime] = None
        self.incident_fire_count = 0
        self.last_error: Optional[str] = None

    def update_config(self, config: DeterrenceConfig) -> None:
        self.config = config

    def handle_bark_detection(self, score: float, audio_level: float) -> list[DeterrenceEvent]:
        if not self.config.auto_enabled:
            return []
        if score < self.config.bark_score_threshold:
            return []
        if self._quiet_hours_active():
            return []
        if self._cooldown_remaining() > 0:
            return []
        if self.incident_fire_count >= self.config.max_fires_per_incident:
            return []
        if self._successful_fires_today() >= self.config.max_fires_per_day:
            return []

        return self._fire(
            source="auto",
            modes=self._enabled_modes(),
            bark_score=score,
            audio_level=audio_level,
            count_for_incident=True,
        )

    def manual_fire(self, modes: Iterable[str]) -> list[DeterrenceEvent]:
        if not self.config.manual_enabled:
            return [
                self._record_event(
                    source="manual",
                    mode="none",
                    status="failed",
                    error="manual deterrence is disabled",
                )
            ]
        return self._fire(source="manual", modes=self._normalize_modes(modes))

    def reset_incident(self) -> None:
        self.incident_fire_count = 0

    def status(self) -> dict:
        last_event = self.storage.list_deterrence_events(limit=1)
        return {
            "settings": asdict(self.config),
            "enabled_modes": self._enabled_modes(),
            "cooldown_remaining_sec": round(self._cooldown_remaining(), 1),
            "incident_fire_count": self.incident_fire_count,
            "successful_fires_today": self._successful_fires_today(),
            "last_error": self.last_error,
            "last_event": deterrence_event_to_dict(last_event[0]) if last_event else None,
        }

    def _fire(
        self,
        source: str,
        modes: Iterable[str],
        bark_score: Optional[float] = None,
        audio_level: Optional[float] = None,
        count_for_incident: bool = False,
    ) -> list[DeterrenceEvent]:
        normalized_modes = self._normalize_modes(modes)
        if not normalized_modes:
            return [
                self._record_event(
                    source=source,
                    mode="none",
                    bark_score=bark_score,
                    audio_level=audio_level,
                    status="failed",
                    error="no deterrence modes selected",
                )
            ]

        events = []
        any_success = False
        for mode in normalized_modes:
            if mode == "audible" and not self.config.audible_enabled:
                events.append(self._record_mode_failure(source, mode, bark_score, audio_level, "audible deterrence is disabled"))
                continue
            if mode == "ultrasonic" and not self.config.ultrasonic_enabled:
                events.append(self._record_mode_failure(source, mode, bark_score, audio_level, "ultrasonic deterrence is disabled"))
                continue

            result = self._fire_mode(mode)
            status = "fired" if result.success else "failed"
            error = result.error
            if result.success:
                any_success = True
                self.last_error = None
            else:
                self.last_error = error

            events.append(
                self._record_event(
                    source=source,
                    mode=mode,
                    bark_score=bark_score,
                    audio_level=audio_level,
                    status=status,
                    error=error,
                )
            )

        if any_success:
            self.last_fire_at = self.now_func()
            if count_for_incident:
                self.incident_fire_count += 1
        return events

    def _record_mode_failure(
        self,
        source: str,
        mode: str,
        bark_score: Optional[float],
        audio_level: Optional[float],
        error: str,
    ) -> DeterrenceEvent:
        self.last_error = error
        return self._record_event(
            source=source,
            mode=mode,
            bark_score=bark_score,
            audio_level=audio_level,
            status="failed",
            error=error,
        )

    def _fire_mode(self, mode: str) -> ActuatorResult:
        if mode == "audible":
            return self.audible_actuator.fire(self.config)
        if mode == "ultrasonic":
            return self.ultrasonic_actuator.fire(self.config)
        return ActuatorResult(mode, False, f"unsupported deterrence mode: {mode}")

    def _record_event(
        self,
        source: str,
        mode: str,
        status: str,
        bark_score: Optional[float] = None,
        audio_level: Optional[float] = None,
        error: Optional[str] = None,
    ) -> DeterrenceEvent:
        event = DeterrenceEvent(
            fired_at=self.now_func(),
            source=source,
            mode=mode,
            profile=self.config.audible_profile,
            status=status,
            bark_score=bark_score,
            audio_level=audio_level,
            duration_sec=_clamp(self.config.burst_sec, 0.1, 10.0),
            error=error,
        )
        event.id = self.storage.save_deterrence_event(event)
        return event

    def _enabled_modes(self) -> list[str]:
        modes = []
        if self.config.audible_enabled:
            modes.append("audible")
        if self.config.ultrasonic_enabled:
            modes.append("ultrasonic")
        return modes

    def _normalize_modes(self, modes: Iterable[str]) -> list[str]:
        normalized = []
        for mode in modes:
            if mode == "both":
                for enabled_mode in self._enabled_modes():
                    if enabled_mode not in normalized:
                        normalized.append(enabled_mode)
                continue
            if mode in VALID_MODES and mode not in normalized:
                normalized.append(mode)
        return normalized

    def _cooldown_remaining(self) -> float:
        if self.last_fire_at is None:
            return 0.0
        elapsed = (self.now_func() - self.last_fire_at).total_seconds()
        return max(0.0, self.config.cooldown_sec - elapsed)

    def _successful_fires_today(self) -> int:
        now = self.now_func()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return self.storage.count_deterrence_events(start_at=day_start, status="fired")

    def _quiet_hours_active(self) -> bool:
        if not self.config.quiet_hours_enabled:
            return False
        start = _parse_time(self.config.quiet_hours_start)
        end = _parse_time(self.config.quiet_hours_end)
        current = self.now_func().time()
        if start <= end:
            return start <= current < end
        return current >= start or current < end


def build_audible_waveform(profile: str, duration_sec: float, sample_rate: int) -> np.ndarray:
    samples = max(1, int(duration_sec * sample_rate))
    t = np.linspace(0, duration_sec, samples, endpoint=False)
    envelope = np.minimum(1.0, np.minimum(t / 0.03, (duration_sec - t) / 0.05))
    envelope = np.maximum(0.0, envelope)

    if profile == "alarm":
        frequency = np.where((t * 8).astype(int) % 2 == 0, 1800.0, 3200.0)
        phase = 2 * math.pi * np.cumsum(frequency) / sample_rate
    else:
        start_hz = 1800.0
        end_hz = 4600.0
        sweep = start_hz + (end_hz - start_hz) * (t / max(duration_sec, 0.001))
        phase = 2 * math.pi * np.cumsum(sweep) / sample_rate

    return (0.6 * envelope * np.sin(phase)).astype(np.float32)


def deterrence_event_to_dict(event: DeterrenceEvent) -> dict:
    return {
        "id": event.id,
        "fired_at": event.fired_at.isoformat(),
        "source": event.source,
        "mode": event.mode,
        "profile": event.profile,
        "status": event.status,
        "bark_score": event.bark_score,
        "audio_level": event.audio_level,
        "duration_sec": event.duration_sec,
        "error": event.error,
    }


def _parse_time(value: str) -> datetime_time:
    try:
        hour, minute = value.split(":", 1)
        return datetime_time(hour=int(hour), minute=int(minute))
    except (ValueError, TypeError):
        return datetime_time(0, 0)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))
