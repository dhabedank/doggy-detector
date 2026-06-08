import pytest
from pathlib import Path
from datetime import datetime
import tempfile
import zipfile

from src.reports import ReportGenerator, WEASYPRINT_AVAILABLE
from src.storage import Event
from src.config import LocationConfig


@pytest.fixture
def sample_events():
    return [
        Event(
            id=1,
            started_at=datetime(2024, 1, 15, 10, 30, 0),
            ended_at=datetime(2024, 1, 15, 10, 30, 10),
            duration_sec=10.0,
            bark_count=5,
            peak_score=0.87,
            avg_score=0.75,
            direction="left",
            direction_score=0.85,
            clip_path="clips/2024-01-15/10-30-00_000.wav",
            clip_hash="abc123def456",
            weather_temp_f=72.0,
            weather_wind_mph=5.0,
            weather_conditions="clear",
        ),
        Event(
            id=2,
            started_at=datetime(2024, 1, 15, 14, 0, 0),
            ended_at=datetime(2024, 1, 15, 14, 0, 5),
            duration_sec=5.0,
            bark_count=3,
            peak_score=0.72,
            avg_score=0.68,
            direction="right",
            direction_score=0.78,
            clip_path="clips/2024-01-15/14-00-00_000.wav",
            clip_hash="def789ghi012",
            weather_temp_f=75.0,
            weather_wind_mph=8.0,
            weather_conditions="partly cloudy",
        ),
    ]


@pytest.fixture
def location():
    return LocationConfig(
        address="123 Main St, Anytown, USA",
        lat=34.05,
        lon=-118.24,
    )


def test_generate_html_report(sample_events, location):
    generator = ReportGenerator(location)
    html = generator.generate_html(
        events=sample_events,
        start_date=datetime(2024, 1, 15),
        end_date=datetime(2024, 1, 15, 23, 59, 59),
    )
    assert "DOG DETECTOR REPORT" in html
    assert "123 Main St" in html
    assert "Total incidents: 2" in html
    assert "Left direction: 1" in html
    assert "Right direction: 1" in html


@pytest.mark.skipif(not WEASYPRINT_AVAILABLE, reason="weasyprint not installed")
def test_generate_pdf_creates_file(sample_events, location):
    generator = ReportGenerator(location)
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "report.pdf"
        generator.generate_pdf(
            events=sample_events,
            start_date=datetime(2024, 1, 15),
            end_date=datetime(2024, 1, 15, 23, 59, 59),
            output_path=pdf_path,
        )
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 0
