from datetime import datetime

from src.reporting import build_reporting_summary
from src.storage import Event


def test_reporting_summary_builds_evidence_safe_trends():
    events = [
        Event(
            id=1,
            started_at=datetime(2026, 6, 23, 22, 30),
            ended_at=datetime(2026, 6, 23, 22, 30, 20),
            duration_sec=20,
            bark_count=7,
            peak_score=0.31,
            avg_score=0.2,
            detection_threshold=0.29,
            direction="left",
            clip_path="clips/2026-06-23/a.wav",
            bark_markers=[{"time_sec": 4.0}],
        ),
        Event(
            id=2,
            started_at=datetime(2026, 6, 23, 22, 36),
            ended_at=datetime(2026, 6, 23, 22, 37),
            duration_sec=60,
            bark_count=16,
            peak_score=0.7,
            avg_score=0.44,
            direction="right",
            clip_path="clips/2026-06-23/b.wav",
            weather_conditions="clear",
        ),
        Event(
            id=3,
            started_at=datetime(2026, 6, 24, 8, 0),
            ended_at=datetime(2026, 6, 24, 8, 3, 30),
            duration_sec=210,
            bark_count=30,
            peak_score=0.9,
            avg_score=0.5,
            direction="left",
            clip_path=None,
            weather_conditions="wind",
        ),
    ]

    summary = build_reporting_summary(
        events,
        start=datetime(2026, 6, 23, 0, 0),
        end=datetime(2026, 6, 24, 23, 59, 59),
        include_false_pos=False,
        false_positive_count=1,
        total_event_count=4,
        clip_exists=lambda event: event.id == 1,
        quiet_start="22:00",
        quiet_end="07:00",
        cluster_gap_minutes=10,
    )

    assert summary["kpis"]["incident_count"] == 3
    assert summary["kpis"]["total_event_count"] == 4
    assert summary["kpis"]["false_positive_count"] == 1
    assert summary["kpis"]["total_duration_sec"] == 290
    assert summary["kpis"]["missing_clip_count"] == 2
    assert summary["kpis"]["near_threshold_count"] == 1
    assert summary["quiet_hours"]["incident_count"] == 2
    assert summary["clusters"][0]["incident_count"] == 2
    assert summary["daily"][0]["incident_count"] == 2
    assert summary["hourly"][22]["incident_count"] == 2
    assert summary["duration_buckets"][-1]["incident_count"] == 1
    assert summary["direction_summary"][0]["label"] == "left"

    payload_text = str(summary).lower()
    assert "bark_count" not in payload_text
    assert "bark_markers" not in payload_text
