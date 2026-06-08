"""API routes for the web dashboard."""

import io
import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

router = APIRouter()


class FlagRequest(BaseModel):
    """Request body for flagging an event as false positive."""
    reason: Optional[str] = None


@router.get("/")
async def get_dashboard(request: Request):
    """Serve main dashboard HTML."""
    templates = request.app.state.templates
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}


@router.get("/api/status")
async def get_status(request: Request):
    """Return detector status including uptime."""
    # Return basic status - uptime could be tracked in a separate module
    # For now, return a simple status response
    return {
        "status": "running",
        "uptime_seconds": 0,  # Would be tracked by detector in production
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


@router.post("/api/reports/generate")
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
