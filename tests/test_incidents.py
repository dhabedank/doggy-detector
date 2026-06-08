import pytest
from datetime import datetime, timedelta

from src.incidents import IncidentTracker, IncidentState, Detection
from src.config import IncidentsConfig


@pytest.fixture
def config():
    return IncidentsConfig(
        min_barks=2,
        gap_sec=3.0,
        min_duration_sec=0.1,
        merge_within_sec=10.0,
    )


@pytest.fixture
def tracker(config):
    return IncidentTracker(config)


def test_single_detection_no_incident(tracker):
    now = datetime.now()
    detection = Detection(timestamp=now, score=0.8, direction="left", direction_score=0.9)
    incident = tracker.process_detection(detection)
    assert incident is None
    assert tracker.state == IncidentState.MONITORING


def test_two_detections_starts_incident(tracker):
    now = datetime.now()
    d1 = Detection(timestamp=now, score=0.8, direction="left", direction_score=0.9)
    d2 = Detection(timestamp=now + timedelta(seconds=0.5), score=0.85, direction="left", direction_score=0.85)
    tracker.process_detection(d1)
    incident = tracker.process_detection(d2)
    assert incident is None  # Still in progress
    assert tracker.state == IncidentState.ACTIVE


def test_incident_tracks_threshold_and_audio_level(tracker):
    now = datetime.now()
    d1 = Detection(
        timestamp=now,
        score=0.08,
        direction="left",
        direction_score=0.9,
        threshold=0.05,
        audio_level=0.2,
    )
    d2 = Detection(
        timestamp=now + timedelta(seconds=0.5),
        score=0.11,
        direction="left",
        direction_score=0.85,
        threshold=0.05,
        audio_level=0.4,
    )
    tracker.process_detection(d1)
    tracker.process_detection(d2)
    tracker.check_timeout(now + timedelta(seconds=4.0))

    incident = tracker.check_timeout(now + timedelta(seconds=14.0))

    assert incident is not None
    assert incident.detection_threshold == 0.05
    assert incident.peak_audio_level == 0.4
    assert incident.avg_audio_level == pytest.approx(0.3)


def test_gap_ends_incident(tracker):
    now = datetime.now()
    d1 = Detection(timestamp=now, score=0.8, direction="left", direction_score=0.9)
    d2 = Detection(timestamp=now + timedelta(seconds=0.5), score=0.85, direction="left", direction_score=0.85)
    tracker.process_detection(d1)
    tracker.process_detection(d2)
    incident = tracker.check_timeout(now + timedelta(seconds=4.0))
    assert incident is None
    assert tracker.state == IncidentState.COOLDOWN

    incident = tracker.check_timeout(now + timedelta(seconds=14.0))
    assert incident is not None
    assert incident.bark_count == 2
    assert incident.peak_score == 0.85
    assert tracker.state == IncidentState.MONITORING


def test_short_incident_discarded(tracker):
    tracker.config.min_duration_sec = 2.0
    now = datetime.now()
    d1 = Detection(timestamp=now, score=0.8, direction="left", direction_score=0.9)
    d2 = Detection(timestamp=now + timedelta(seconds=0.3), score=0.85, direction="left", direction_score=0.85)
    tracker.process_detection(d1)
    tracker.process_detection(d2)
    incident = tracker.check_timeout(now + timedelta(seconds=4.0))
    assert incident is None
    assert tracker.state == IncidentState.COOLDOWN

    incident = tracker.check_timeout(now + timedelta(seconds=14.0))
    assert incident is None
    assert tracker.state == IncidentState.MONITORING


def test_single_detection_times_out_without_incident(tracker):
    now = datetime.now()
    d1 = Detection(timestamp=now, score=0.8, direction="left", direction_score=0.9)
    tracker.process_detection(d1)

    incident = tracker.check_timeout(now + timedelta(seconds=4.0))

    assert incident is None
    assert tracker.state == IncidentState.MONITORING
    assert tracker.detections == []


def test_merge_window_extends_incident(tracker):
    now = datetime.now()
    d1 = Detection(timestamp=now, score=0.8, direction="left", direction_score=0.9)
    d2 = Detection(timestamp=now + timedelta(seconds=0.5), score=0.85, direction="left", direction_score=0.85)
    d3 = Detection(timestamp=now + timedelta(seconds=8.0), score=0.9, direction="right", direction_score=0.7)

    tracker.process_detection(d1)
    tracker.process_detection(d2)
    assert tracker.check_timeout(now + timedelta(seconds=4.0)) is None
    assert tracker.state == IncidentState.COOLDOWN

    assert tracker.process_detection(d3) is None
    assert tracker.state == IncidentState.ACTIVE

    assert tracker.check_timeout(now + timedelta(seconds=12.0)) is None
    assert tracker.state == IncidentState.COOLDOWN

    incident = tracker.check_timeout(now + timedelta(seconds=22.0))
    assert incident is not None
    assert incident.bark_count == 3
    assert incident.peak_score == 0.9


def test_detection_inside_gap_plus_merge_window_extends_incident(tracker):
    now = datetime.now()
    d1 = Detection(timestamp=now, score=0.8, direction="left", direction_score=0.9)
    d2 = Detection(timestamp=now + timedelta(seconds=0.5), score=0.85, direction="left", direction_score=0.85)
    d3 = Detection(timestamp=now + timedelta(seconds=12.0), score=0.9, direction="right", direction_score=0.7)

    tracker.process_detection(d1)
    tracker.process_detection(d2)
    assert tracker.check_timeout(now + timedelta(seconds=4.0)) is None
    assert tracker.state == IncidentState.COOLDOWN

    incident = tracker.process_detection(d3)

    assert incident is None
    assert tracker.state == IncidentState.ACTIVE
    assert len(tracker.detections) == 3


def test_detection_after_gap_plus_merge_window_starts_new_incident(tracker):
    now = datetime.now()
    d1 = Detection(timestamp=now, score=0.8, direction="left", direction_score=0.9)
    d2 = Detection(timestamp=now + timedelta(seconds=0.5), score=0.85, direction="left", direction_score=0.85)
    d3 = Detection(timestamp=now + timedelta(seconds=14.0), score=0.9, direction="right", direction_score=0.7)

    tracker.process_detection(d1)
    tracker.process_detection(d2)
    assert tracker.check_timeout(now + timedelta(seconds=4.0)) is None
    assert tracker.state == IncidentState.COOLDOWN

    incident = tracker.process_detection(d3)

    assert incident is not None
    assert incident.bark_count == 2
    assert tracker.state == IncidentState.MONITORING
    assert tracker.detections == [d3]


def test_detection_after_merge_respects_min_barks_one():
    config = IncidentsConfig(
        min_barks=1,
        gap_sec=3.0,
        min_duration_sec=0.1,
        merge_within_sec=10.0,
    )
    tracker = IncidentTracker(config)
    now = datetime.now()
    d1 = Detection(timestamp=now, score=0.8, direction="left", direction_score=0.9)
    d2 = Detection(timestamp=now + timedelta(seconds=14.0), score=0.9, direction="right", direction_score=0.7)

    tracker.process_detection(d1)
    assert tracker.state == IncidentState.ACTIVE
    assert tracker.check_timeout(now + timedelta(seconds=4.0)) is None
    assert tracker.state == IncidentState.COOLDOWN

    incident = tracker.process_detection(d2)

    assert incident is None
    assert tracker.state == IncidentState.ACTIVE
    assert tracker.detections == [d2]
