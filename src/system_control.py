"""Narrow system controls for the installed detector service."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Any


DETECTOR_SERVICE = "doggy-detector"


def queue_detector_restart(
    *,
    service_name: str = DETECTOR_SERVICE,
    delay_sec: float = 1.0,
    popen: Any = subprocess.Popen,
) -> dict[str, Any]:
    """Queue a detached systemd restart after the HTTP response can flush."""
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return {
            "queued": False,
            "service": service_name,
            "error": "systemctl is not available on this machine",
        }

    command = [systemctl, "restart", service_name]
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        command = ["sudo", "-n", *command]

    launcher = [
        sys.executable,
        "-c",
        (
            "import subprocess, time\n"
            f"time.sleep({max(0.0, float(delay_sec))!r})\n"
            f"raise SystemExit(subprocess.run({command!r}).returncode)\n"
        ),
    ]

    try:
        process = popen(
            launcher,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except Exception as exc:
        return {
            "queued": False,
            "service": service_name,
            "error": str(exc),
        }

    return {
        "queued": True,
        "service": service_name,
        "pid": process.pid,
        "delay_sec": delay_sec,
        "error": None,
    }
