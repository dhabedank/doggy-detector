"""Runtime health checks for the detector."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.config import Config
from src.storage import Storage

STATE_ORDER = {"ok": 0, "warn": 1, "critical": 2, "unknown": 3}


def build_health(
    config: Config,
    storage: Storage,
    detector: Optional[Any] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build a health summary with named checks."""
    generated_at = now or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    checks: list[dict[str, str]] = []
    status = getattr(detector, "status", {}) if detector is not None else {}

    _add_detector_checks(checks, detector, status, generated_at, config)
    _add_deterrence_checks(checks, detector, config)
    _add_disk_check(checks, storage.data_dir)
    _add_temperature_check(checks)
    _add_load_check(checks)
    _add_clock_sync_check(checks)

    state = _overall_state(check["state"] for check in checks)
    return {
        "state": state,
        "generated_at": generated_at.isoformat(),
        "checks": checks,
    }


def _add_check(checks: list[dict[str, str]], name: str, state: str, message: str) -> None:
    checks.append({"name": name, "state": state, "message": message})


def _overall_state(states) -> str:
    strongest = "ok"
    for state in states:
        if STATE_ORDER.get(state, 0) > STATE_ORDER[strongest]:
            strongest = state
    return strongest


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _add_detector_checks(
    checks: list[dict[str, str]],
    detector: Optional[Any],
    status: dict[str, Any],
    now: datetime,
    config: Config,
) -> None:
    if detector is None:
        _add_check(checks, "detector", "unknown", "Detector is not attached to the web app")
        return

    running = bool(getattr(detector, "_running", False))
    if running:
        _add_check(checks, "detector", "ok", "Detector process loop is running")
    else:
        _add_check(checks, "detector", "warn", "Detector is initialized but not running")

    audio_error = status.get("audio_error")
    if audio_error:
        _add_check(checks, "audio_error", "critical", str(audio_error))
    else:
        _add_check(checks, "audio_error", "ok", "No audio errors reported")

    chunks_processed = int(status.get("chunks_processed", 0) or 0)
    startup_at = _parse_datetime(status.get("startup_at"))
    if running and startup_at and chunks_processed == 0:
        seconds_since_start = (now - startup_at).total_seconds()
        if seconds_since_start > max(10.0, config.detection.window_sec * 4):
            _add_check(checks, "audio_chunks", "critical", "No audio chunks received after startup")
        else:
            _add_check(checks, "audio_chunks", "warn", "Waiting for first audio chunk")
    else:
        _add_check(checks, "audio_chunks", "ok", f"{chunks_processed} chunks processed")

    last_audio_at = _parse_datetime(status.get("last_audio_chunk_at"))
    if running and chunks_processed > 0 and last_audio_at:
        stale_after = max(10.0, config.detection.window_sec * 10)
        age_sec = (now - last_audio_at).total_seconds()
        if age_sec > stale_after:
            _add_check(checks, "stale_audio", "critical", f"No audio chunk for {age_sec:.0f} seconds")
        else:
            _add_check(checks, "stale_audio", "ok", "Audio chunks are current")
    else:
        _add_check(checks, "stale_audio", "ok", "No stale audio evidence")

    if status.get("mono_mode"):
        _add_check(checks, "mono_mode", "warn", "Running in mono mode; direction detection is unavailable")
    else:
        _add_check(checks, "mono_mode", "ok", "Stereo mode available")

    audio_level = float(status.get("audio_level", 0.0) or 0.0)
    if chunks_processed > 0 and audio_level < 0.005:
        _add_check(checks, "silent_audio", "warn", "Microphone input is nearly silent")
    else:
        _add_check(checks, "silent_audio", "ok", "Microphone input level is present")

    left_level = status.get("left_level")
    right_level = status.get("right_level")
    if left_level is not None and right_level is not None:
        left = float(left_level or 0.0)
        right = float(right_level or 0.0)
        weaker = min(left, right)
        stronger = max(left, right)
        if stronger > 0.02 and (weaker <= 0.001 or stronger / max(weaker, 0.001) > 6.0):
            _add_check(checks, "channel_balance", "warn", "One microphone channel is much weaker")
        else:
            _add_check(checks, "channel_balance", "ok", "Microphone channels look balanced")
    else:
        _add_check(checks, "channel_balance", "ok", "Channel balance is not yet measured")

    if status.get("clipping"):
        _add_check(checks, "clipping", "warn", "Audio input is clipping")
    else:
        _add_check(checks, "clipping", "ok", "No clipping detected")

    queue_drops = int(status.get("queue_drops", 0) or 0)
    if queue_drops > 0:
        _add_check(checks, "queue_drops", "warn", f"{queue_drops} audio chunks were dropped")
    else:
        _add_check(checks, "queue_drops", "ok", "No queue drops")


def _add_deterrence_checks(checks: list[dict[str, str]], detector: Optional[Any], config: Config) -> None:
    deterrence = config.deterrence
    enabled_modes = []
    if deterrence.audible_enabled:
        enabled_modes.append("audible")
    if deterrence.ultrasonic_enabled:
        enabled_modes.append("ultrasonic")

    if deterrence.auto_enabled and not enabled_modes:
        _add_check(checks, "deterrence", "warn", "Auto deterrence is armed but no output mode is enabled")
    elif deterrence.auto_enabled:
        _add_check(checks, "deterrence", "ok", f"Auto deterrence armed for {', '.join(enabled_modes)}")
    elif deterrence.manual_enabled:
        _add_check(checks, "deterrence", "ok", "Manual deterrence controls are available")
    else:
        _add_check(checks, "deterrence", "ok", "Deterrence is disabled")

    if deterrence.ultrasonic_enabled and deterrence.ultrasonic_gpio_pin is None:
        _add_check(checks, "ultrasonic_trigger", "warn", "Ultrasonic mode is enabled but no GPIO pin is configured")
    elif deterrence.ultrasonic_enabled:
        _add_check(checks, "ultrasonic_trigger", "ok", f"Ultrasonic trigger uses GPIO {deterrence.ultrasonic_gpio_pin}")
    else:
        _add_check(checks, "ultrasonic_trigger", "ok", "Ultrasonic trigger is disabled")

    controller = getattr(detector, "deterrence_controller", None)
    if controller is not None and getattr(controller, "last_error", None):
        _add_check(checks, "deterrence_last_error", "warn", str(controller.last_error))
    else:
        _add_check(checks, "deterrence_last_error", "ok", "No deterrence actuator errors reported")


def _add_disk_check(checks: list[dict[str, str]], data_dir: Path) -> None:
    usage = shutil.disk_usage(data_dir)
    free_mb = usage.free / (1024 * 1024)
    if free_mb < 100:
        state = "critical"
    elif free_mb < 500:
        state = "warn"
    else:
        state = "ok"
    _add_check(checks, "disk_free", state, f"{free_mb:.0f} MB free")


def _add_temperature_check(checks: list[dict[str, str]]) -> None:
    temp_path = Path("/sys/class/thermal/thermal_zone0/temp")
    if not temp_path.exists():
        _add_check(checks, "pi_temperature", "ok", "Temperature sensor is not available")
        return

    try:
        temp_c = int(temp_path.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        _add_check(checks, "pi_temperature", "unknown", "Temperature sensor could not be read")
        return

    if temp_c >= 80:
        state = "critical"
    elif temp_c >= 70:
        state = "warn"
    else:
        state = "ok"
    _add_check(checks, "pi_temperature", state, f"{temp_c:.1f} C")


def _add_load_check(checks: list[dict[str, str]]) -> None:
    if not hasattr(os, "getloadavg"):
        _add_check(checks, "load_average", "ok", "Load average is not available")
        return

    one_min, _, _ = os.getloadavg()
    cores = os.cpu_count() or 1
    if one_min > cores * 4:
        state = "critical"
    elif one_min > cores * 2:
        state = "warn"
    else:
        state = "ok"
    _add_check(checks, "load_average", state, f"1-minute load {one_min:.2f} on {cores} cores")


def _add_clock_sync_check(checks: list[dict[str, str]]) -> None:
    try:
        result = subprocess.run(
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        _add_check(checks, "clock_sync", "ok", "Clock sync status is not available")
        return

    value = result.stdout.strip().lower()
    if value == "yes":
        _add_check(checks, "clock_sync", "ok", "System clock is synchronized")
    elif value == "no":
        _add_check(checks, "clock_sync", "warn", "System clock is not synchronized")
    else:
        _add_check(checks, "clock_sync", "ok", "Clock sync status is not available")
