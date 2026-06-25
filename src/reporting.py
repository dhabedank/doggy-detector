"""Trend reporting helpers for stored incidents."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, time, timedelta
from typing import Any, Callable, Iterable

from src.storage import Event


ClipExists = Callable[[Event], bool]


DURATION_BUCKETS = (
    ("0-10s", 0, 10),
    ("10-30s", 10, 30),
    ("30-60s", 30, 60),
    ("1-3m", 60, 180),
    ("3m+", 180, None),
)


def build_reporting_summary(
    events: Iterable[Event],
    *,
    start: datetime,
    end: datetime,
    include_false_pos: bool,
    false_positive_count: int = 0,
    total_event_count: int | None = None,
    clip_exists: ClipExists | None = None,
    quiet_start: str = "22:00",
    quiet_end: str = "07:00",
    cluster_gap_minutes: int = 10,
) -> dict[str, Any]:
    """Build evidence-safe aggregate reports for a selected time range."""
    event_list = sorted(events, key=lambda event: event.started_at)
    durations = [_event_duration(event) for event in event_list]
    total_duration = sum(durations)
    elapsed_sec = max(0.0, (end - start).total_seconds())
    incident_count = len(event_list)
    total_count = total_event_count if total_event_count is not None else incident_count
    quiet_start_time = parse_hhmm(quiet_start)
    quiet_end_time = parse_hhmm(quiet_end)

    return {
        "range": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "elapsed_sec": round(elapsed_sec, 3),
            "include_false_pos": include_false_pos,
        },
        "kpis": _build_kpis(
            event_list,
            durations,
            total_duration,
            elapsed_sec,
            false_positive_count=false_positive_count,
            total_event_count=total_count,
            clip_exists=clip_exists,
        ),
        "daily": _build_daily(event_list, start, end),
        "hourly": _build_hourly(event_list),
        "heatmap": _build_heatmap(event_list, start, end),
        "duration_buckets": _build_duration_buckets(durations),
        "quiet_hours": _build_quiet_hours(
            event_list,
            quiet_start=quiet_start_time,
            quiet_end=quiet_end_time,
        ),
        "clusters": _build_clusters(event_list, cluster_gap_minutes=cluster_gap_minutes),
        "longest_incidents": _build_longest_incidents(event_list),
        "direction_summary": _build_category_summary(event_list, "direction", "Unknown"),
        "weather_summary": _build_category_summary(event_list, "weather_conditions", "Unknown"),
        "busiest_days": _build_busiest_days(event_list),
        "busiest_hours": _build_busiest_hours(event_list),
    }


def parse_hhmm(value: str) -> time:
    """Parse a HH:MM value used by reporting quiet-hour filters."""
    hour_text, minute_text = value.split(":", 1)
    hour = int(hour_text)
    minute = int(minute_text)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("time must be HH:MM")
    return time(hour=hour, minute=minute)


def _build_kpis(
    events: list[Event],
    durations: list[float],
    total_duration: float,
    elapsed_sec: float,
    *,
    false_positive_count: int,
    total_event_count: int,
    clip_exists: ClipExists | None,
) -> dict[str, Any]:
    incident_count = len(events)
    scores = [float(event.peak_score) for event in events if event.peak_score is not None]
    clip_count = sum(1 for event in events if _event_has_clip(event, clip_exists))
    missing_clip_count = incident_count - clip_count
    near_threshold_count = sum(1 for event in events if _near_threshold(event))

    return {
        "incident_count": incident_count,
        "total_event_count": int(total_event_count),
        "false_positive_count": int(false_positive_count),
        "total_duration_sec": round(total_duration, 3),
        "longest_duration_sec": round(max(durations, default=0.0), 3),
        "avg_duration_sec": round(total_duration / incident_count, 3) if incident_count else 0.0,
        "median_duration_sec": round(_percentile(durations, 50), 3),
        "p90_duration_sec": round(_percentile(durations, 90), 3),
        "incident_rate_per_hour": round(incident_count / (elapsed_sec / 3600), 3) if elapsed_sec > 0 else 0.0,
        "incident_rate_per_day": round(incident_count / (elapsed_sec / 86400), 3) if elapsed_sec > 0 else 0.0,
        "duration_percent_elapsed": round((total_duration / elapsed_sec) * 100, 3) if elapsed_sec > 0 else 0.0,
        "avg_peak_score": round(sum(scores) / len(scores), 3) if scores else 0.0,
        "max_peak_score": round(max(scores, default=0.0), 3),
        "recorded_clip_count": clip_count,
        "missing_clip_count": missing_clip_count,
        "near_threshold_count": near_threshold_count,
    }


def _build_daily(events: list[Event], start: datetime, end: datetime) -> list[dict[str, Any]]:
    rows = {
        day.isoformat(): {
            "date": day.isoformat(),
            "incident_count": 0,
            "duration_sec": 0.0,
            "longest_duration_sec": 0.0,
            "avg_peak_score": 0.0,
            "_score_total": 0.0,
            "_score_count": 0,
        }
        for day in _date_range(start, end)
    }

    for event in events:
        key = event.started_at.date().isoformat()
        row = rows.setdefault(
            key,
            {
                "date": key,
                "incident_count": 0,
                "duration_sec": 0.0,
                "longest_duration_sec": 0.0,
                "avg_peak_score": 0.0,
                "_score_total": 0.0,
                "_score_count": 0,
            },
        )
        duration = _event_duration(event)
        row["incident_count"] += 1
        row["duration_sec"] += duration
        row["longest_duration_sec"] = max(row["longest_duration_sec"], duration)
        if event.peak_score is not None:
            row["_score_total"] += float(event.peak_score)
            row["_score_count"] += 1

    daily = []
    for row in rows.values():
        score_count = row.pop("_score_count")
        score_total = row.pop("_score_total")
        row["duration_sec"] = round(row["duration_sec"], 3)
        row["longest_duration_sec"] = round(row["longest_duration_sec"], 3)
        row["avg_peak_score"] = round(score_total / score_count, 3) if score_count else 0.0
        daily.append(row)

    return sorted(daily, key=lambda row: row["date"])


def _build_hourly(events: list[Event]) -> list[dict[str, Any]]:
    rows = {
        hour: {
            "hour": hour,
            "incident_count": 0,
            "duration_sec": 0.0,
            "avg_duration_sec": 0.0,
            "avg_peak_score": 0.0,
            "_score_total": 0.0,
            "_score_count": 0,
        }
        for hour in range(24)
    }

    for event in events:
        row = rows[event.started_at.hour]
        duration = _event_duration(event)
        row["incident_count"] += 1
        row["duration_sec"] += duration
        if event.peak_score is not None:
            row["_score_total"] += float(event.peak_score)
            row["_score_count"] += 1

    hourly = []
    for row in rows.values():
        score_count = row.pop("_score_count")
        score_total = row.pop("_score_total")
        incident_count = row["incident_count"]
        row["duration_sec"] = round(row["duration_sec"], 3)
        row["avg_duration_sec"] = round(row["duration_sec"] / incident_count, 3) if incident_count else 0.0
        row["avg_peak_score"] = round(score_total / score_count, 3) if score_count else 0.0
        hourly.append(row)

    return hourly


def _build_heatmap(events: list[Event], start: datetime, end: datetime) -> list[dict[str, Any]]:
    rows = {
        (day.isoformat(), hour): {
            "date": day.isoformat(),
            "hour": hour,
            "incident_count": 0,
            "duration_sec": 0.0,
        }
        for day in _date_range(start, end)
        for hour in range(24)
    }

    for event in events:
        key = (event.started_at.date().isoformat(), event.started_at.hour)
        row = rows.setdefault(
            key,
            {
                "date": key[0],
                "hour": key[1],
                "incident_count": 0,
                "duration_sec": 0.0,
            },
        )
        row["incident_count"] += 1
        row["duration_sec"] += _event_duration(event)

    heatmap = []
    for row in rows.values():
        row["duration_sec"] = round(row["duration_sec"], 3)
        heatmap.append(row)

    return sorted(heatmap, key=lambda row: (row["date"], row["hour"]))


def _build_duration_buckets(durations: list[float]) -> list[dict[str, Any]]:
    rows = []
    for label, minimum, maximum in DURATION_BUCKETS:
        if maximum is None:
            matching = [duration for duration in durations if duration >= minimum]
        else:
            matching = [duration for duration in durations if minimum <= duration < maximum]
        rows.append(
            {
                "label": label,
                "min_sec": minimum,
                "max_sec": maximum,
                "incident_count": len(matching),
                "duration_sec": round(sum(matching), 3),
            }
        )
    return rows


def _build_quiet_hours(
    events: list[Event],
    *,
    quiet_start: time,
    quiet_end: time,
) -> dict[str, Any]:
    quiet_events = [
        event for event in events
        if _time_in_window(event.started_at.time(), quiet_start, quiet_end)
    ]
    total_events = len(events)
    total_quiet_duration = sum(_event_duration(event) for event in quiet_events)
    total_duration = sum(_event_duration(event) for event in events)
    return {
        "start": quiet_start.strftime("%H:%M"),
        "end": quiet_end.strftime("%H:%M"),
        "incident_count": len(quiet_events),
        "duration_sec": round(total_quiet_duration, 3),
        "longest_duration_sec": round(max((_event_duration(event) for event in quiet_events), default=0.0), 3),
        "incident_percent": round((len(quiet_events) / total_events) * 100, 3) if total_events else 0.0,
        "duration_percent": round((total_quiet_duration / total_duration) * 100, 3) if total_duration > 0 else 0.0,
    }


def _build_clusters(events: list[Event], *, cluster_gap_minutes: int) -> list[dict[str, Any]]:
    if not events:
        return []

    gap_sec = max(0, cluster_gap_minutes) * 60
    clusters: list[dict[str, Any]] = []
    current = _new_cluster(events[0])

    for event in events[1:]:
        gap = max(0.0, (event.started_at - current["ended_at"]).total_seconds())
        if gap <= gap_sec:
            current["incident_count"] += 1
            current["duration_sec"] += _event_duration(event)
            current["ended_at"] = max(current["ended_at"], event.ended_at)
            current["max_gap_sec"] = max(current["max_gap_sec"], gap)
            current["event_ids"].append(event.id)
        else:
            clusters.append(current)
            current = _new_cluster(event)
    clusters.append(current)

    repeat_clusters = [cluster for cluster in clusters if cluster["incident_count"] > 1]
    output = []
    for cluster in repeat_clusters:
        span_sec = max(0.0, (cluster["ended_at"] - cluster["started_at"]).total_seconds())
        output.append(
            {
                "started_at": cluster["started_at"].isoformat(),
                "ended_at": cluster["ended_at"].isoformat(),
                "span_sec": round(span_sec, 3),
                "incident_count": cluster["incident_count"],
                "duration_sec": round(cluster["duration_sec"], 3),
                "max_gap_sec": round(cluster["max_gap_sec"], 3),
                "event_ids": cluster["event_ids"],
            }
        )
    return sorted(output, key=lambda row: row["started_at"], reverse=True)[:20]


def _build_longest_incidents(events: list[Event]) -> list[dict[str, Any]]:
    longest = sorted(events, key=_event_duration, reverse=True)[:10]
    return [_event_to_report_dict(event) for event in longest]


def _build_category_summary(
    events: list[Event],
    attribute: str,
    fallback: str,
) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "label": "",
            "incident_count": 0,
            "duration_sec": 0.0,
            "longest_duration_sec": 0.0,
        }
    )
    for event in events:
        label = getattr(event, attribute, None) or fallback
        row = rows[str(label)]
        row["label"] = str(label)
        duration = _event_duration(event)
        row["incident_count"] += 1
        row["duration_sec"] += duration
        row["longest_duration_sec"] = max(row["longest_duration_sec"], duration)

    output = []
    for row in rows.values():
        row["duration_sec"] = round(row["duration_sec"], 3)
        row["longest_duration_sec"] = round(row["longest_duration_sec"], 3)
        output.append(row)

    return sorted(output, key=lambda row: (row["incident_count"], row["duration_sec"]), reverse=True)


def _build_busiest_days(events: list[Event]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"date": "", "incident_count": 0, "duration_sec": 0.0, "longest_duration_sec": 0.0}
    )
    for event in events:
        key = event.started_at.date().isoformat()
        row = rows[key]
        row["date"] = key
        duration = _event_duration(event)
        row["incident_count"] += 1
        row["duration_sec"] += duration
        row["longest_duration_sec"] = max(row["longest_duration_sec"], duration)

    output = []
    for row in rows.values():
        row["duration_sec"] = round(row["duration_sec"], 3)
        row["longest_duration_sec"] = round(row["longest_duration_sec"], 3)
        output.append(row)

    return sorted(output, key=lambda row: (row["incident_count"], row["duration_sec"]), reverse=True)[:7]


def _build_busiest_hours(events: list[Event]) -> list[dict[str, Any]]:
    rows = _build_hourly(events)
    return sorted(rows, key=lambda row: (row["incident_count"], row["duration_sec"]), reverse=True)[:5]


def _event_to_report_dict(event: Event) -> dict[str, Any]:
    return {
        "id": event.id,
        "started_at": event.started_at.isoformat(),
        "ended_at": event.ended_at.isoformat(),
        "duration_sec": round(_event_duration(event), 3),
        "peak_score": event.peak_score,
        "avg_score": event.avg_score,
        "detection_threshold": event.detection_threshold,
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


def _new_cluster(event: Event) -> dict[str, Any]:
    return {
        "started_at": event.started_at,
        "ended_at": event.ended_at,
        "incident_count": 1,
        "duration_sec": _event_duration(event),
        "max_gap_sec": 0.0,
        "event_ids": [event.id],
    }


def _event_duration(event: Event) -> float:
    return max(0.0, float(event.duration_sec or 0.0))


def _event_has_clip(event: Event, clip_exists: ClipExists | None) -> bool:
    if not event.clip_path:
        return False
    if clip_exists is None:
        return True
    return bool(clip_exists(event))


def _near_threshold(event: Event) -> bool:
    if event.detection_threshold is None or event.peak_score is None:
        return False
    return 0 <= float(event.peak_score) - float(event.detection_threshold) <= 0.05


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = max(0, min(len(sorted_values) - 1, math.ceil((percentile / 100) * len(sorted_values)) - 1))
    return sorted_values[index]


def _time_in_window(value: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= value < end
    return value >= start or value < end


def _date_range(start: datetime, end: datetime):
    current = start.date()
    final = end.date()
    while current <= final:
        yield current
        current += timedelta(days=1)
