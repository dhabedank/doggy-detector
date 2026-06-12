"""API routes for the web dashboard."""

import asyncio
import io
import json
import math
import subprocess
import zipfile
from dataclasses import asdict
from datetime import datetime
from typing import Optional, Any

from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

try:
    from sse_starlette.sse import EventSourceResponse
except ImportError:
    EventSourceResponse = None

from src.health import build_health
from src.deterrence import deterrence_event_to_dict
from src.updater import (
    check_for_updates,
    queue_update_request,
    read_update_status,
    trigger_update_service,
)
from src.web.auth import authenticate_user, clear_auth_cookie, set_auth_cookie

try:
    import sounddevice as sd
except ImportError:
    sd = None

router = APIRouter()

LOG_SERVICES = {
    "app": {"unit": "doggy-detector", "label": "Detector"},
    "updater": {"unit": "doggy-detector-updater", "label": "Updater"},
    "update-check": {"unit": "doggy-detector-update-check", "label": "Update Check"},
}


class FlagRequest(BaseModel):
    """Request body for flagging an event as false positive."""
    reason: Optional[str] = None


class LoginRequest(BaseModel):
    """Request body for dashboard login."""
    username: str
    password: str


class SettingsUpdate(BaseModel):
    """Request body for updating settings."""
    audio_device: Optional[Any] = None
    detection_threshold: Optional[float] = None
    incidents_min_barks: Optional[int] = None
    incidents_gap_sec: Optional[float] = None
    incidents_merge_within_sec: Optional[float] = None
    incidents_min_duration_sec: Optional[float] = None
    incidents_pre_roll_sec: Optional[float] = None
    location_address: Optional[str] = None
    location_lat: Optional[float] = None
    location_lon: Optional[float] = None


class DeterrenceSettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    audible_enabled: Optional[bool] = None
    ultrasonic_enabled: Optional[bool] = None
    manual_enabled: Optional[bool] = None
    auto_enabled: Optional[bool] = None
    assertiveness: Optional[str] = None
    bark_score_threshold: Optional[float] = None
    cooldown_sec: Optional[float] = None
    burst_sec: Optional[float] = None
    max_fires_per_incident: Optional[int] = None
    max_fires_per_day: Optional[int] = None
    quiet_hours_enabled: Optional[bool] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    ultrasonic_gpio_pin: Optional[int] = None
    ultrasonic_active_high: Optional[bool] = None
    audible_output_device: Optional[Any] = None
    audible_profile: Optional[str] = None


class DeterrenceFireRequest(BaseModel):
    modes: list[str] = Field(default_factory=lambda: ["both"])


class UpdateRequest(BaseModel):
    target: str = "latest"


@router.get("/")
async def get_dashboard(request: Request):
    """Serve main dashboard HTML."""
    templates = request.app.state.templates
    return templates.TemplateResponse(request=request, name="index.html")


@router.get("/settings")
async def get_settings_page(request: Request):
    """Serve full settings page."""
    templates = request.app.state.templates
    return templates.TemplateResponse(request=request, name="settings.html")


@router.get("/logs")
async def get_logs_page(request: Request):
    """Serve service logs page."""
    templates = request.app.state.templates
    return templates.TemplateResponse(request=request, name="logs.html")


@router.get("/health")
async def health_check(request: Request):
    """Public health check endpoint."""
    health = build_health(
        config=request.app.state.config,
        storage=request.app.state.storage,
        detector=getattr(request.app.state, "detector", None),
    )
    status_code = 200 if health["state"] in {"ok", "warn"} else 503
    return JSONResponse(health, status_code=status_code)


@router.get("/login", response_class=HTMLResponse)
async def get_login():
    """Serve a minimal login page."""
    return """
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Doggy Detector Login</title>
        <link rel="stylesheet" href="/static/style.css">
    </head>
    <body class="login-page">
        <main class="login-panel">
            <h1>Doggy Detector</h1>
            <form id="loginForm">
                <label for="username">Username</label>
                <input id="username" name="username" type="text" autocomplete="username" required autofocus>
                <label for="password">Password</label>
                <input id="password" name="password" type="password" autocomplete="current-password" required>
                <button class="btn btn-primary" type="submit">Log In</button>
                <p id="loginError" class="login-error" hidden>Invalid username or password.</p>
            </form>
        </main>
        <script>
        document.getElementById('loginForm').addEventListener('submit', async (event) => {
            event.preventDefault();
            const response = await fetch('/api/auth/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    username: document.getElementById('username').value,
                    password: document.getElementById('password').value
                })
            });
            if (response.ok) {
                window.location.href = '/';
            } else {
                document.getElementById('loginError').hidden = false;
            }
        });
        </script>
    </body>
    </html>
    """


@router.post("/api/auth/login")
async def login(request: Request, login_request: LoginRequest):
    """Validate dashboard credentials and set auth cookie."""
    settings_store = request.app.state.settings_store
    if not authenticate_user(login_request.username, login_request.password, settings_store):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    response = JSONResponse({"success": True})
    set_auth_cookie(response, request.app.state.auth_manager, login_request.username)
    return response


@router.post("/api/auth/logout")
async def logout():
    """Clear auth cookie."""
    response = JSONResponse({"success": True})
    clear_auth_cookie(response)
    return response


@router.get("/api/status")
async def get_status(request: Request):
    """Return detector status including current audio device and live detection info."""
    return _build_status_payload(request)


@router.get("/api/status/stream")
async def stream_status(request: Request):
    """Stream live status updates via Server-Sent Events."""
    async def event_generator():
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            data = _build_status_payload(request)

            yield {"event": "status", "data": json.dumps(data)}
            await asyncio.sleep(0.5)  # Update every 500ms

    if EventSourceResponse is None:
        async def fallback_generator():
            async for event in event_generator():
                yield f"event: {event['event']}\ndata: {event['data']}\n\n"

        return StreamingResponse(fallback_generator(), media_type="text/event-stream")

    return EventSourceResponse(event_generator())


@router.get("/api/devices")
async def list_devices():
    """List available audio input devices."""
    if sd is None:
        return {"devices": [], "error": "sounddevice not available"}

    try:
        devices = sd.query_devices()
        input_devices = []
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0:
                hostapi_name = sd.query_hostapis(d["hostapi"])["name"]
                input_devices.append({
                    "id": i,
                    "name": d["name"],
                    "hostapi": hostapi_name,
                    "key": f"{d['name']}, {hostapi_name}",
                    "channels": d["max_input_channels"],
                    "is_stereo": d["max_input_channels"] >= 2,
                })
        return {"devices": input_devices}
    except Exception as e:
        return {"devices": [], "error": str(e)}


@router.get("/api/settings")
async def get_settings(request: Request):
    """Get current settings."""
    config = request.app.state.config
    return {
        "audio": {
            "device": config.audio.device,
            "sample_rate": config.audio.sample_rate,
        },
        "detection": {
            "threshold": config.detection.threshold,
            "window_sec": config.detection.window_sec,
        },
        "incidents": {
            "min_barks": config.incidents.min_barks,
            "gap_sec": config.incidents.gap_sec,
            "merge_within_sec": config.incidents.merge_within_sec,
            "min_duration_sec": config.incidents.min_duration_sec,
            "pre_roll_sec": config.incidents.pre_roll_sec,
            "finalize_after_sec": config.incidents.gap_sec + config.incidents.merge_within_sec,
        },
        "location": {
            "address": config.location.address,
            "lat": config.location.lat,
            "lon": config.location.lon,
        },
        "deterrence": asdict(config.deterrence),
    }


@router.post("/api/settings")
async def update_settings(request: Request, settings: SettingsUpdate):
    """Update settings and save to SQLite."""
    config = request.app.state.config
    settings_store = request.app.state.settings_store

    # Update values if provided
    if settings.audio_device is not None:
        # Convert "auto" to system default, otherwise save a stable device key.
        if isinstance(settings.audio_device, str) and settings.audio_device.strip().lower() in {"", "auto"}:
            config.audio.device = None
        else:
            try:
                device_id = int(settings.audio_device)
                config.audio.device = device_id
            except (TypeError, ValueError):
                config.audio.device = settings.audio_device

    if settings.detection_threshold is not None:
        threshold = max(0.001, min(1.0, settings.detection_threshold))
        config.detection.threshold = threshold
        detector = getattr(request.app.state, "detector", None)
        if detector is not None and hasattr(detector, "detector"):
            detector.detector.threshold = threshold

    if settings.incidents_min_barks is not None:
        config.incidents.min_barks = max(1, min(20, int(settings.incidents_min_barks)))

    if settings.incidents_gap_sec is not None:
        config.incidents.gap_sec = max(1.0, min(120.0, float(settings.incidents_gap_sec)))

    if settings.incidents_merge_within_sec is not None:
        config.incidents.merge_within_sec = max(0.0, min(180.0, float(settings.incidents_merge_within_sec)))

    if settings.incidents_min_duration_sec is not None:
        config.incidents.min_duration_sec = max(0.0, min(60.0, float(settings.incidents_min_duration_sec)))

    if settings.incidents_pre_roll_sec is not None:
        pre_roll = float(settings.incidents_pre_roll_sec)
        allowed_pre_roll = {5.0, 10.0, 15.0, 20.0}
        config.incidents.pre_roll_sec = pre_roll if pre_roll in allowed_pre_roll else config.incidents.pre_roll_sec

    if settings.location_address is not None:
        config.location.address = settings.location_address

    if settings.location_lat is not None:
        if settings.location_lat < -90 or settings.location_lat > 90:
            raise HTTPException(status_code=400, detail="Latitude must be between -90 and 90")
        config.location.lat = settings.location_lat

    if settings.location_lon is not None:
        if settings.location_lon < -180 or settings.location_lon > 180:
            raise HTTPException(status_code=400, detail="Longitude must be between -180 and 180")
        config.location.lon = settings.location_lon

    settings_store.update_config(config)

    return {
        "success": True,
        "message": "Settings saved. Restart only if you changed the microphone device.",
    }


@router.get("/api/deterrence/settings")
async def get_deterrence_settings(request: Request):
    """Get deterrence settings and live state."""
    controller = request.app.state.deterrence_controller
    return controller.status()


@router.post("/api/deterrence/settings")
async def update_deterrence_settings(request: Request, settings: DeterrenceSettingsUpdate):
    """Update deterrence settings and apply them to the live controller."""
    config = request.app.state.config
    deterrence = config.deterrence

    if settings.enabled is not None:
        deterrence.enabled = bool(settings.enabled)
    if settings.audible_enabled is not None:
        deterrence.audible_enabled = bool(settings.audible_enabled)
    if settings.ultrasonic_enabled is not None:
        deterrence.ultrasonic_enabled = bool(settings.ultrasonic_enabled)
    if settings.manual_enabled is not None:
        deterrence.manual_enabled = bool(settings.manual_enabled)
    if settings.auto_enabled is not None:
        deterrence.auto_enabled = bool(settings.auto_enabled)
    if settings.assertiveness is not None:
        deterrence.assertiveness = settings.assertiveness if settings.assertiveness in {"assertive", "conservative", "custom"} else "custom"
    if settings.bark_score_threshold is not None:
        deterrence.bark_score_threshold = _clamp_float(settings.bark_score_threshold, 0.001, 1.0)
    if settings.cooldown_sec is not None:
        deterrence.cooldown_sec = _clamp_float(settings.cooldown_sec, 0.0, 3600.0)
    if settings.burst_sec is not None:
        deterrence.burst_sec = _clamp_float(settings.burst_sec, 0.1, 10.0)
    if settings.max_fires_per_incident is not None:
        deterrence.max_fires_per_incident = _clamp_int(settings.max_fires_per_incident, 1, 100)
    if settings.max_fires_per_day is not None:
        deterrence.max_fires_per_day = _clamp_int(settings.max_fires_per_day, 1, 1000)
    if settings.quiet_hours_enabled is not None:
        deterrence.quiet_hours_enabled = bool(settings.quiet_hours_enabled)
    if settings.quiet_hours_start is not None:
        deterrence.quiet_hours_start = _validate_hhmm(settings.quiet_hours_start, "quiet_hours_start")
    if settings.quiet_hours_end is not None:
        deterrence.quiet_hours_end = _validate_hhmm(settings.quiet_hours_end, "quiet_hours_end")
    if settings.ultrasonic_active_high is not None:
        deterrence.ultrasonic_active_high = bool(settings.ultrasonic_active_high)
    if "ultrasonic_gpio_pin" in settings.model_fields_set:
        deterrence.ultrasonic_gpio_pin = (
            None
            if settings.ultrasonic_gpio_pin is None
            else _clamp_int(settings.ultrasonic_gpio_pin, 0, 27)
        )
    if "audible_output_device" in settings.model_fields_set:
        deterrence.audible_output_device = _normalize_optional_device(settings.audible_output_device)
    if settings.audible_profile is not None:
        deterrence.audible_profile = settings.audible_profile if settings.audible_profile in {"chirp", "alarm"} else "chirp"

    request.app.state.settings_store.update_config(config)
    request.app.state.deterrence_controller.update_config(deterrence)

    return {
        "success": True,
        "deterrence": asdict(deterrence),
        "status": request.app.state.deterrence_controller.status(),
    }


@router.post("/api/deterrence/fire")
async def fire_deterrence(request: Request, fire_request: DeterrenceFireRequest):
    """Manually fire one or more deterrence modes."""
    controller = request.app.state.deterrence_controller
    events = controller.manual_fire(fire_request.modes)
    return {
        "success": any(event.status == "fired" for event in events),
        "events": [deterrence_event_to_dict(event) for event in events],
        "status": controller.status(),
    }


@router.get("/api/deterrence/events")
async def list_deterrence_events(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
):
    """List recent deterrence firing attempts."""
    events = request.app.state.storage.list_deterrence_events(limit=limit)
    return {"events": [deterrence_event_to_dict(event) for event in events]}


@router.get("/api/update/status")
async def get_update_status(request: Request):
    """Return current version, latest known release, and updater state."""
    return read_update_status(
        project_dir=request.app.state.project_dir,
        data_dir=request.app.state.storage.data_dir,
    )


@router.post("/api/update/check")
async def check_update_status(request: Request):
    """Check GitHub release tags now."""
    try:
        return check_for_updates(
            project_dir=request.app.state.project_dir,
            data_dir=request.app.state.storage.data_dir,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Update check failed: {exc}")


@router.post("/api/update/request")
async def request_update_install(request: Request, update_request: UpdateRequest):
    """Queue an update request and ask systemd to run the updater service."""
    status = queue_update_request(
        target=update_request.target,
        project_dir=request.app.state.project_dir,
        data_dir=request.app.state.storage.data_dir,
    )
    trigger = trigger_update_service()
    status["service_trigger"] = trigger
    return status


@router.get("/api/logs")
async def get_service_logs(
    service: str = Query("app"),
    lines: int = Query(200, ge=20, le=1000),
):
    """Return recent journal lines for a whitelisted service."""
    if service not in LOG_SERVICES:
        raise HTTPException(status_code=400, detail="Unknown log service")

    spec = LOG_SERVICES[service]
    command = [
        "journalctl",
        "-u",
        spec["unit"],
        "-n",
        str(lines),
        "--no-pager",
        "-o",
        "short-iso",
    ]
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            command,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except FileNotFoundError:
        return {
            "success": False,
            "service": service,
            "unit": spec["unit"],
            "label": spec["label"],
            "lines": [],
            "error": "journalctl is not available",
            "generated_at": datetime.now().isoformat(),
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "service": service,
            "unit": spec["unit"],
            "label": spec["label"],
            "lines": [],
            "error": "journalctl timed out",
            "generated_at": datetime.now().isoformat(),
        }

    stdout_lines = result.stdout.splitlines()
    stderr_lines = result.stderr.splitlines()
    return {
        "success": result.returncode == 0,
        "service": service,
        "unit": spec["unit"],
        "label": spec["label"],
        "lines": stdout_lines,
        "error": None if result.returncode == 0 else "\n".join(stderr_lines[-4:]) or f"journalctl exited {result.returncode}",
        "generated_at": datetime.now().isoformat(),
    }


@router.get("/api/summary")
async def get_summary(request: Request):
    """Return dashboard summary cards for today and all time."""
    storage = request.app.state.storage
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    return {
        "today": storage.summarize_events(
            start_date=today_start,
            end_date=today_end,
            include_false_pos=False,
        ),
        "all_time": storage.summarize_events(include_false_pos=False),
    }


@router.get("/api/events")
async def list_events(
    request: Request,
    date: Optional[str] = Query(None, description="Date filter in YYYY-MM-DD format"),
    include_false_pos: bool = Query(True, description="Include false positives in results"),
    only_false_pos: bool = Query(False, description="Return only false positives"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(20, ge=1, le=100, description="Results per page"),
):
    """List events with pagination and filters."""
    storage = request.app.state.storage

    # Parse date filter if provided
    start_date = None
    end_date = None

    if date:
        try:
            parsed_date = datetime.strptime(date, "%Y-%m-%d")
            start_date = parsed_date
            # End of day for the same date
            end_date = parsed_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    # Calculate offset for pagination
    offset = (page - 1) * per_page

    # Get total count
    total = storage.count_events(
        start_date=start_date,
        end_date=end_date,
        include_false_pos=include_false_pos,
        only_false_pos=only_false_pos,
    )

    # Get paginated events
    events = storage.list_events(
        start_date=start_date,
        end_date=end_date,
        include_false_pos=include_false_pos,
        only_false_pos=only_false_pos,
        limit=per_page,
        offset=offset,
    )

    event_dicts = [_event_to_dict(event) for event in events]

    return {
        "total": total,
        "total_pages": max(1, math.ceil(total / per_page)),
        "page": page,
        "per_page": per_page,
        "events": event_dicts,
}


@router.get("/api/events/{event_id}")
async def get_event(
    request: Request,
    event_id: int,
):
    """Get one event for the detail modal."""
    storage = request.app.state.storage
    event = storage.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return _event_to_dict(event)


@router.post("/api/events/{event_id}/flag")
async def flag_event(
    request: Request,
    event_id: int,
    flag_request: FlagRequest,
):
    """Flag an event as a false positive."""
    storage = request.app.state.storage

    # Check if event exists
    event = storage.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Flag the event
    storage.flag_false_positive(event_id, reason=flag_request.reason)

    return {
        "id": event_id,
        "is_false_pos": True,
        "false_pos_reason": flag_request.reason,
    }


@router.post("/api/events/{event_id}/unflag")
async def unflag_event(
    request: Request,
    event_id: int,
):
    """Remove false positive flag from an event."""
    storage = request.app.state.storage

    # Check if event exists
    event = storage.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Unflag the event
    storage.unflag_false_positive(event_id)

    return {
        "id": event_id,
        "is_false_pos": False,
        "false_pos_reason": None,
    }


@router.delete("/api/events/{event_id}")
async def delete_event(
    request: Request,
    event_id: int,
):
    """Delete an event row and its referenced clip."""
    storage = request.app.state.storage
    deleted_event = storage.delete_event(event_id)
    if not deleted_event:
        raise HTTPException(status_code=404, detail="Event not found")

    return {
        "id": event_id,
        "deleted": True,
        "clip_path": deleted_event.clip_path,
    }


@router.get("/api/clips/{date}/{filename}")
async def get_clip(
    request: Request,
    date: str,
    filename: str,
):
    """Serve audio clip file."""
    storage = request.app.state.storage

    # Validate date format
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    # Build clip path
    clip_path = storage.data_dir / "clips" / date / filename

    # Security: ensure the requested path is within the clips directory
    try:
        clip_path = clip_path.resolve()
        expected_parent = (storage.data_dir / "clips").resolve()
        clip_path.relative_to(expected_parent)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    # Check if file exists
    if not clip_path.exists():
        raise HTTPException(status_code=404, detail="Clip not found")

    # Serve the file
    return FileResponse(
        path=clip_path,
        filename=filename,
        media_type="audio/wav",
    )


@router.get("/api/reports/generate")
async def generate_report(
    request: Request,
    start_date: str = Query(..., description="Start date in YYYY-MM-DD format"),
    end_date: str = Query(..., description="End date in YYYY-MM-DD format"),
):
    """Generate a report for a date range and return as ZIP download."""
    storage = request.app.state.storage

    # Parse and validate dates
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        # Set end to end of day
        end = end.replace(hour=23, minute=59, second=59, microsecond=999999)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    if start > end:
        raise HTTPException(status_code=400, detail="start_date must be before end_date")

    # Check if reports module exists and can be imported
    try:
        from src.reports import generate_events_csv, generate_pdf_report
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Reports module not available",
        )

    # Generate report
    try:
        events = storage.list_events(
            start_date=start,
            end_date=end,
            include_false_pos=False,
            limit=10000,
            offset=0,
        )
        pdf_data = generate_pdf_report(
            events=events,
            config=request.app.state.config,
            start_date=start,
            end_date=end,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate report: {str(e)}",
        )

    # Create ZIP file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        # Add PDF report
        filename = f"report_{start_date}_to_{end_date}.pdf"
        zip_file.writestr(filename, pdf_data)

        # Add CSV data for the same non-false-positive events included in the report
        csv_filename = f"events_{start_date}_to_{end_date}.csv"
        zip_file.writestr(csv_filename, generate_events_csv(events))

        # Add only clips referenced by non-false-positive events in this report
        for event in events:
            if not event.clip_path:
                continue
            clip_file = (storage.data_dir / event.clip_path).resolve()
            try:
                clip_file.relative_to(storage.data_dir.resolve())
            except ValueError:
                continue
            if clip_file.exists() and clip_file.is_file():
                zip_file.write(clip_file, arcname=event.clip_path)

    zip_buffer.seek(0)

    return StreamingResponse(
        iter([zip_buffer.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=dog_detector_report_{start_date}_to_{end_date}.zip"},
    )


@router.get("/api/reports/csv")
async def export_csv(
    request: Request,
    start_date: str = Query(..., description="Start date in YYYY-MM-DD format"),
    end_date: str = Query(..., description="End date in YYYY-MM-DD format"),
):
    """Export events as CSV."""
    storage = request.app.state.storage

    # Parse dates
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        end = end.replace(hour=23, minute=59, second=59, microsecond=999999)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    # Get events
    events = storage.list_events(
        start_date=start,
        end_date=end,
        include_false_pos=True,
        limit=10000,
        offset=0,
    )

    from src.reports import generate_events_csv

    csv_content = generate_events_csv(events)

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=dog_detector_events_{start_date}_to_{end_date}.csv"},
    )


def _build_status_payload(request: Request) -> dict[str, Any]:
    config = request.app.state.config
    detector = getattr(request.app.state, "detector", None)
    deterrence_controller = request.app.state.deterrence_controller

    current_device = config.audio.device
    device_name = "System default input"

    if sd is not None:
        try:
            devices = sd.query_devices()
            if current_device is not None:
                if isinstance(current_device, int) and current_device < len(devices):
                    device_name = devices[current_device]["name"]
                elif isinstance(current_device, str):
                    try:
                        matched = sd.query_devices(current_device, kind="input")
                        device_name = f"{matched['name']} (pinned)"
                    except Exception:
                        device_name = f"{current_device} (missing)"
            else:
                default_device = sd.query_devices(kind="input")
                device_name = f"{default_device['name']} (system default)"
        except Exception:
            device_name = "Unknown"

    live_status = {}
    if detector and hasattr(detector, "status"):
        live_status = {
            "startup_at": detector.status.get("startup_at"),
            "last_score": float(round(detector.status.get("last_score", 0), 3)),
            "audio_level": float(round(detector.status.get("audio_level", 0), 3)),
            "is_barking": bool(detector.status.get("is_barking", False)),
            "active_incident": bool(detector.status.get("active_incident", False)),
            "chunks_processed": int(detector.status.get("chunks_processed", 0)),
            "last_detection_time": detector.status.get("last_detection_time"),
            "last_audio_chunk_at": detector.status.get("last_audio_chunk_at"),
            "audio_error": detector.status.get("audio_error"),
            "mono_mode": bool(detector.status.get("mono_mode", False)),
            "queue_drops": int(detector.status.get("queue_drops", 0) or 0),
        }

    health = build_health(
        config=config,
        storage=request.app.state.storage,
        detector=detector,
    )

    return {
        "status": "running" if not live_status.get("audio_error") else "error",
        "audio_device": device_name,
        "threshold": config.detection.threshold,
        "health": health,
        "deterrence": deterrence_controller.status(),
        **live_status,
    }


def _event_to_dict(event) -> dict[str, Any]:
    return {
        "id": event.id,
        "started_at": event.started_at.isoformat(),
        "ended_at": event.ended_at.isoformat(),
        "duration_sec": event.duration_sec,
        "bark_count": event.bark_count,
        "peak_score": event.peak_score,
        "avg_score": event.avg_score,
        "detection_threshold": event.detection_threshold,
        "peak_audio_level": event.peak_audio_level,
        "avg_audio_level": event.avg_audio_level,
        "direction": event.direction,
        "direction_score": event.direction_score,
        "clip_path": event.clip_path,
        "clip_hash": event.clip_hash,
        "is_false_pos": event.is_false_pos,
        "false_pos_reason": event.false_pos_reason,
        "weather_temp_f": event.weather_temp_f,
        "weather_wind_mph": event.weather_wind_mph,
        "weather_conditions": event.weather_conditions,
        "clip_url": f"/api/{event.clip_path}" if event.clip_path else None,
    }


def _clamp_float(value: float, low: float, high: float) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        raise HTTPException(status_code=400, detail="Value must be finite")
    return max(low, min(high, numeric))


def _clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _validate_hhmm(value: str, field_name: str) -> str:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (AttributeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{field_name} must be HH:MM")
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise HTTPException(status_code=400, detail=f"{field_name} must be HH:MM")
    return f"{hour:02d}:{minute:02d}"


def _normalize_optional_device(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "auto"}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return value
