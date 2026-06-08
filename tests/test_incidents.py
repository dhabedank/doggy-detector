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


def test_gap_ends_incident(tracker):
    now = datetime.now()
    d1 = Detection(timestamp=now, score=0.8, direction="left", direction_score=0.9)
    d2 = Detection(timestamp=now + timedelta(seconds=0.5), score=0.85, direction="left", direction_score=0.85)
    tracker.process_detection(d1)
    tracker.process_detection(d2)
    incident = tracker.check_timeout(now + timedelta(seconds=4.0))
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
    assert tracker.state == IncidentState.MONITORING
