"""API routes for the web dashboard."""

import asyncio
import io
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

try:
    import sounddevice as sd
except ImportError:
    sd = None

router = APIRouter()


class FlagRequest(BaseModel):
    """Request body for flagging an event as false positive."""
    reason: Optional[str] = None


class SettingsUpdate(BaseModel):
    """Request body for updating settings."""
    audio_device: Optional[str] = None
    detection_threshold: Optional[float] = None
    location_address: Optional[str] = None
    location_lat: Optional[float] = None
    location_lon: Optional[float] = None


@router.get("/")
async def get_dashboard(request: Request):
    """Serve main dashboard HTML."""
    templates = request.app.state.templates
    return templates.TemplateResponse(request=request, name="index.html")


@router.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}


@router.post("/api/test-audio")
async def test_audio(request: Request):
    """Test the detector with a sample audio file."""
    import numpy as np
    from pathlib import Path

    detector = getattr(request.app.state, "detector", None)
    if not detector:
        raise HTTPException(status_code=503, detail="Detector not available")

    # Find test file
    test_file = Path("tests/barking-test-file.mp3")
    if not test_file.exists():
        raise HTTPException(status_code=404, detail="Test file not found")

    try:
        from pydub import AudioSegment

        # Load MP3
        audio = AudioSegment.from_mp3(test_file)

        # Convert to 16kHz mono
        audio = audio.set_frame_rate(16000).set_channels(1)

        # Convert to numpy float32 array
        samples = np.array(audio.get_array_of_samples()).astype(np.float32)
        samples = samples / 32768.0  # Normalize to -1 to 1

        # Process in chunks (0.5 second chunks like live audio)
        chunk_size = 8000  # 0.5 seconds at 16kHz
        results = []

        for i in range(0, len(samples), chunk_size):
            chunk = samples[i:i + chunk_size]
            if len(chunk) < chunk_size // 2:
                continue

            result = detector.detector.detect(chunk)
            results.append({
                "time_sec": round(i / 16000, 2),
                "score": round(float(result.score), 3),
                "is_bark": bool(result.is_bark),
                "top_classes": result.top_classes,
            })

        # Summary
        max_score = max(r["score"] for r in results) if results else 0
        bark_count = sum(1 for r in results if r["is_bark"])

        return {
            "success": True,
            "file": str(test_file),
            "duration_sec": round(len(samples) / 16000, 2),
            "chunks_analyzed": len(results),
            "max_score": max_score,
            "bark_detections": bark_count,
            "threshold": detector.detector.threshold,
            "details": results,
        }

    except ImportError:
        raise HTTPException(status_code=503, detail="pydub not installed. Run: pip install pydub")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing audio: {str(e)}")


@router.get("/api/status")
async def get_status(request: Request):
    """Return detector status including current audio device and live detection info."""
    config = request.app.state.config
    detector = getattr(request.app.state, "detector", None)

    # Get current device info
    current_device = config.audio.device
    device_name = "Auto-detect"

    if sd is not None:
        try:
            devices = sd.query_devices()
            if current_device is not None:
                if isinstance(current_device, int) and current_device < len(devices):
                    device_name = devices[current_device]["name"]
                elif isinstance(current_device, str):
                    device_name = current_device
            else:
                # Find what would be auto-selected
                for i, d in enumerate(devices):
                    if d["max_input_channels"] >= 2:
                        device_name = f"{d['name']} (auto)"
                        break
        except Exception:
            device_name = "Unknown"

    # Get live status from detector if available
    live_status = {}
    if detector and hasattr(detector, "status"):
        live_status = {
            "last_score": float(round(detector.status.get("last_score", 0), 3)),
            "audio_level": float(round(detector.status.get("audio_level", 0), 3)),
            "is_barking": bool(detector.status.get("is_barking", False)),
            "active_incident": bool(detector.status.get("active_incident", False)),
            "chunks_processed": int(detector.status.get("chunks_processed", 0)),
            "last_detection_time": detector.status.get("last_detection_time"),
            "audio_error": detector.status.get("audio_error"),
            "mono_mode": bool(detector.status.get("mono_mode", False)),
        }

    return {
        "status": "running" if not live_status.get("audio_error") else "error",
        "audio_device": device_name,
        "threshold": config.detection.threshold,
        **live_status,
    }


@router.get("/api/status/stream")
async def stream_status(request: Request):
    """Stream live status updates via Server-Sent Events."""
    config = request.app.state.config
    detector = getattr(request.app.state, "detector", None)

    async def event_generator():
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            # Build status data
            current_device = config.audio.device
            device_name = "Auto-detect"

            if sd is not None:
                try:
                    devices = sd.query_devices()
                    if current_device is not None:
                        if isinstance(current_device, int) and current_device < len(devices):
                            device_name = devices[current_device]["name"]
                    else:
                        for i, d in enumerate(devices):
                            if d["max_input_channels"] >= 2:
                                device_name = f"{d['name']} (auto)"
                                break
                except Exception:
                    pass

            live_status = {}
            if detector and hasattr(detector, "status"):
                live_status = {
                    "last_score": float(round(detector.status.get("last_score", 0), 3)),
                    "audio_level": float(round(detector.status.get("audio_level", 0), 3)),
                    "is_barking": bool(detector.status.get("is_barking", False)),
                    "active_incident": bool(detector.status.get("active_incident", False)),
                    "chunks_processed": int(detector.status.get("chunks_processed", 0)),
                    "last_detection_time": detector.status.get("last_detection_time"),
                    "audio_error": detector.status.get("audio_error"),
                    "mono_mode": bool(detector.status.get("mono_mode", False)),
                }

            data = {
                "status": "running" if not live_status.get("audio_error") else "error",
                "audio_device": device_name,
                "threshold": config.detection.threshold,
                **live_status,
            }

            yield {"event": "status", "data": json.dumps(data)}
            await asyncio.sleep(0.5)  # Update every 500ms

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
                input_devices.append({
                    "id": i,
                    "name": d["name"],
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
        },
        "location": {
            "address": config.location.address,
            "lat": config.location.lat,
            "lon": config.location.lon,
        },
    }


@router.post("/api/settings")
async def update_settings(request: Request, settings: SettingsUpdate):
    """Update settings and save to config file."""
    import yaml

    config = request.app.state.config
    config_path = Path("config.yaml")

    # Read current config file
    if config_path.exists():
        with open(config_path) as f:
            file_config = yaml.safe_load(f) or {}
    else:
        file_config = {}

    # Ensure sections exist
    file_config.setdefault("audio", {})
    file_config.setdefault("detection", {})
    file_config.setdefault("location", {})

    # Update values if provided
    if settings.audio_device is not None:
        # Convert "auto" to null, otherwise try to parse as int
        if settings.audio_device.lower() == "auto":
            file_config["audio"]["device"] = None
            config.audio.device = None
        else:
            try:
                device_id = int(settings.audio_device)
                file_config["audio"]["device"] = device_id
                config.audio.device = device_id
            except ValueError:
                file_config["audio"]["device"] = settings.audio_device
                config.audio.device = settings.audio_device

    if settings.detection_threshold is not None:
        threshold = max(0.01, min(1.0, settings.detection_threshold))
        file_config["detection"]["threshold"] = threshold
        config.detection.threshold = threshold

    if settings.location_address is not None:
        file_config["location"]["address"] = settings.location_address
        config.location.address = settings.location_address

    if settings.location_lat is not None:
        file_config["location"]["lat"] = settings.location_lat
        config.location.lat = settings.location_lat

    if settings.location_lon is not None:
        file_config["location"]["lon"] = settings.location_lon
        config.location.lon = settings.location_lon

    # Save to file
    with open(config_path, "w") as f:
        yaml.dump(file_config, f, default_flow_style=False, sort_keys=False)

    return {
        "success": True,
        "message": "Settings saved. Restart the detector for audio device changes to take effect.",
    }


@router.get("/api/events")
async def list_events(
    request: Request,
    date: Optional[str] = Query(None, description="Date filter in YYYY-MM-DD format"),
    include_false_pos: bool = Query(True, description="Include false positives in results"),
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
    )

    # Get paginated events
    events = storage.list_events(
        start_date=start_date,
        end_date=end_date,
        include_false_pos=include_false_pos,
        limit=per_page,
        offset=offset,
    )

    # Format events for response
    event_dicts = []
    for event in events:
        event_dicts.append({
            "id": event.id,
            "started_at": event.started_at.isoformat(),
            "ended_at": event.ended_at.isoformat(),
            "duration_sec": event.duration_sec,
            "bark_count": event.bark_count,
            "peak_score": event.peak_score,
            "avg_score": event.avg_score,
            "direction": event.direction,
            "direction_score": event.direction_score,
            "clip_path": event.clip_path,
            "is_false_pos": event.is_false_pos,
            "false_pos_reason": event.false_pos_reason,
            "weather_temp_f": event.weather_temp_f,
            "weather_wind_mph": event.weather_wind_mph,
            "weather_conditions": event.weather_conditions,
        })

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "events": event_dicts,
    }


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


@router.get("/api/clips/{date}/{filename}")
async def get_clip(
    request: Request,
    date: str,
    filename: str,
):
    """Serve audio clip file."""
    storage = request.app.state.storage
    config = request.app.state.config

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
        if not str(clip_path).startswith(str(expected_parent)):
            raise HTTPException(status_code=403, detail="Access denied")
    except Exception:
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
        from src.reports import generate_pdf_report
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Reports module not available",
        )

    # Generate report
    try:
        pdf_data = generate_pdf_report(
            events=storage.list_events(
                start_date=start,
                end_date=end,
                include_false_pos=False,
                limit=10000,
                offset=0,
            ),
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

        # Add clips from date range
        clips_dir = storage.data_dir / "clips"
        if clips_dir.exists():
            for clip_file in clips_dir.glob(f"*/*"):
                if clip_file.is_file():
                    try:
                        file_date_str = clip_file.parent.name
                        file_date = datetime.strptime(file_date_str, "%Y-%m-%d")
                        if start <= file_date <= end:
                            arcname = f"clips/{clip_file.parent.name}/{clip_file.name}"
                            zip_file.write(clip_file, arcname=arcname)
                    except (ValueError, OSError):
                        # Skip files that can't be processed
                        continue

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
    import csv
    from io import StringIO

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

    # Build CSV
    output = StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "ID", "Started At", "Ended At", "Duration (sec)", "Bark Count",
        "Peak Score", "Avg Score", "Direction", "Direction Score",
        "Clip Path", "False Positive", "False Pos Reason",
        "Weather Temp (F)", "Weather Wind (mph)", "Weather Conditions"
    ])

    # Data rows
    for event in events:
        writer.writerow([
            event.id,
            event.started_at.isoformat(),
            event.ended_at.isoformat(),
            round(event.duration_sec, 2),
            event.bark_count,
            round(event.peak_score, 3),
            round(event.avg_score, 3),
            event.direction or "",
            round(event.direction_score, 3) if event.direction_score else "",
            event.clip_path or "",
            event.is_false_pos,
            event.false_pos_reason or "",
            event.weather_temp_f or "",
            event.weather_wind_mph or "",
            event.weather_conditions or "",
        ])

    csv_content = output.getvalue()

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=dog_detector_events_{start_date}_to_{end_date}.csv"},
    )
