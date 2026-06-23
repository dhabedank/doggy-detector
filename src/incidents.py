"""Incident tracking state machine for grouping bark detections."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from statistics import mean

from src.config import IncidentsConfig


class IncidentState(Enum):
    """State of the incident tracker."""
    MONITORING = "monitoring"
    ACTIVE = "active"
    COOLDOWN = "cooldown"


@dataclass
class Detection:
    """A single bark detection."""
    timestamp: datetime
    score: float
    direction: str
    direction_score: float
    threshold: Optional[float] = None
    audio_level: Optional[float] = None


@dataclass
class Incident:
    """A grouped incident of multiple barks."""
    started_at: datetime
    ended_at: datetime
    bark_count: int
    peak_score: float
    avg_score: float
    direction: str
    direction_score: float
    detection_threshold: Optional[float] = None
    peak_audio_level: Optional[float] = None
    avg_audio_level: Optional[float] = None
    detections: list = field(default_factory=list)

    @property
    def duration_sec(self) -> float:
        """Duration of the incident in seconds."""
        return (self.ended_at - self.started_at).total_seconds()


class IncidentTracker:
    """State machine for tracking bark incidents."""

    def __init__(self, config: IncidentsConfig):
        """Initialize the incident tracker.

        Args:
            config: Incidents configuration
        """
        self.config = config
        self.state = IncidentState.MONITORING
        self.detections = []
        self.last_detection_time = None
        self.cooldown_started_at = None
        self.last_discard_reason = None

    def process_detection(self, detection: Detection) -> Optional[Incident]:
        """Process a bark detection and update state.

        Args:
            detection: The detection to process

        Returns:
            An incident if one was completed, None otherwise
        """
        self.last_discard_reason = None

        if self.state == IncidentState.MONITORING:
            self._clear_stale_monitoring_detections(detection.timestamp)

        if self.state in {IncidentState.ACTIVE, IncidentState.COOLDOWN} and self.last_detection_time is not None:
            gap = (detection.timestamp - self.last_detection_time).total_seconds()
            if gap > self._finalize_after_sec():
                completed = self._finalize_incident()
                self._start_new_detection(detection)
                return completed

            if self.state == IncidentState.COOLDOWN:
                self.state = IncidentState.ACTIVE
                self.cooldown_started_at = None

        self.detections.append(detection)
        self.last_detection_time = detection.timestamp

        # Transition to ACTIVE after min_barks detections
        if len(self.detections) >= self.config.min_barks:
            self.state = IncidentState.ACTIVE

        # Still building the incident
        return None

    def check_timeout(self, current_time: datetime) -> Optional[Incident]:
        """Check if the incident should end due to timeout.

        Args:
            current_time: The current time

        Returns:
            An incident if one was completed and met minimum criteria, None otherwise
        """
        self.last_discard_reason = None

        if self.state == IncidentState.MONITORING:
            self._clear_stale_monitoring_detections(current_time)
            return None

        # Check if gap_sec has elapsed since last detection
        if self.last_detection_time is not None:
            gap = (current_time - self.last_detection_time).total_seconds()
            if self.state == IncidentState.ACTIVE and gap >= self.config.gap_sec:
                self.state = IncidentState.COOLDOWN
                self.cooldown_started_at = current_time
                return None

            if self.state == IncidentState.COOLDOWN and gap >= self._finalize_after_sec():
                return self._finalize_incident()

        return None

    def force_end(self) -> Optional[Incident]:
        """Force end the current incident.

        Returns:
            An incident if one was in progress, None otherwise
        """
        self.last_discard_reason = None

        if self.state == IncidentState.MONITORING:
            self._reset()
            return None

        return self._finalize_incident()

    def _finalize_incident(self) -> Optional[Incident]:
        """Finalize and validate the current incident.

        Returns:
            An incident if it meets minimum criteria, None otherwise
        """
        if not self.detections:
            self._reset()
            return None

        # Calculate incident statistics
        started_at = self.detections[0].timestamp
        ended_at = self.detections[-1].timestamp
        bark_count = len(self.detections)
        scores = [d.score for d in self.detections]
        peak_score = max(scores)
        avg_score = mean(scores)
        audio_levels = [d.audio_level for d in self.detections if d.audio_level is not None]
        thresholds = [d.threshold for d in self.detections if d.threshold is not None]

        # Determine dominant direction by counting
        direction_counts = {}
        direction_scores = {}
        for d in self.detections:
            direction_counts[d.direction] = direction_counts.get(d.direction, 0) + 1
            if d.direction not in direction_scores:
                direction_scores[d.direction] = []
            direction_scores[d.direction].append(d.direction_score)

        # Get dominant direction
        dominant_direction = max(direction_counts, key=direction_counts.get)
        dominant_direction_score = mean(direction_scores[dominant_direction])

        # Check minimum duration
        duration = (ended_at - started_at).total_seconds()
        if duration < self.config.min_duration_sec:
            self.last_discard_reason = "min_duration"
            self._reset()
            return None

        incident = Incident(
            started_at=started_at,
            ended_at=ended_at,
            bark_count=bark_count,
            peak_score=peak_score,
            avg_score=avg_score,
            direction=dominant_direction,
            direction_score=dominant_direction_score,
            detection_threshold=thresholds[-1] if thresholds else None,
            peak_audio_level=max(audio_levels) if audio_levels else None,
            avg_audio_level=mean(audio_levels) if audio_levels else None,
            detections=self.detections.copy(),
        )

        self._reset()
        return incident

    def _reset(self):
        """Reset the tracker to monitoring state."""
        self.state = IncidentState.MONITORING
        self.detections = []
        self.last_detection_time = None
        self.cooldown_started_at = None

    def _start_new_detection(self, detection: Detection):
        """Seed a new potential incident after finalizing an older one."""
        self.detections = [detection]
        self.last_detection_time = detection.timestamp
        self.cooldown_started_at = None
        self.state = (
            IncidentState.ACTIVE
            if len(self.detections) >= self.config.min_barks
            else IncidentState.MONITORING
        )

    def _clear_stale_monitoring_detections(self, current_time: datetime):
        if not self.detections or self.last_detection_time is None:
            return

        gap = (current_time - self.last_detection_time).total_seconds()
        if gap >= self.config.gap_sec:
            self._reset()

    def _finalize_after_sec(self) -> float:
        return self.config.gap_sec + self.config.merge_within_sec
