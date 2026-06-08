"""API routes for the web dashboard."""

import asyncio
import io
import json
import math
import zipfile
from datetime import datetime
from typing import Optional, Any

from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

try:
    from sse_starlette.sse import EventSourceResponse
except ImportError:
    EventSourceResponse = None

from src.health import build_health
from src.web.auth import authenticate_user, clear_auth_cookie, set_auth_cookie

try:
    import sounddevice as sd
except ImportError:
    sd = None

router = APIRouter()


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
