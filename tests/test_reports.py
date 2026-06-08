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
            detection_threshold=0.05,
            peak_audio_level=0.34,
            avg_audio_level=0.22,
            direction="left",
            direction_score=0.85,
            clip_path="clips/2024-01-15/10-30-00_000.wav",
            clip_hash="abc123def4567890fullhash",
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
            clip_hash="def789ghi0123456fullhash",
            weather_temp_f=75.0,
            weather_wind_mph=8.0,
            weather_conditions="partly cloudy",
        ),
        Event(
            id=3,
            started_at=datetime(2024, 1, 15, 16, 0, 0),
            ended_at=datetime(2024, 1, 15, 16, 0, 5),
            duration_sec=5.0,
            bark_count=3,
            peak_score=0.7,
            avg_score=0.6,
            direction="center",
            direction_score=0.5,
            clip_path="clips/2024-01-15/false.wav",
            clip_hash="falsehash",
            is_false_pos=True,
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
    report_events = [event for event in sample_events if not event.is_false_pos]
    html = generator.generate_html(
        events=report_events,
        start_date=datetime(2024, 1, 15),
        end_date=datetime(2024, 1, 15, 23, 59, 59),
    )
    assert "Bark Evidence Report" in html
    assert "<h1>Doggy Detector</h1>" in html
    assert "size: Letter landscape" in html
    assert "123 Main St" in html
    assert '<span class="metric-label">Incidents</span><span class="metric-value">2</span>' in html
    assert "Direction Breakdown" in html
    assert '<div class="direction-card left">' in html
    assert '<div class="direction-card right">' in html
    assert "Report Key" in html
    assert "Model scores run from 0.000 to 1.000" in html
    assert "P is peak score" in html
    assert "first 12 characters" in html
    assert "About This Evidence Package" in html
    assert "YAMNet TensorFlow model" in html
    assert "does not make a legal conclusion" in html
    assert "The ZIP includes the PDF, CSV" in html
    assert "False positives excluded by report filter" not in html
    assert "<th>Score</th>" in html
    assert "T 0.050" in html
    assert "L 0.34" in html
    assert "<th>Clip</th>" in html
    assert "<pre" not in html


@pytest.mark.skipif(not WEASYPRINT_AVAILABLE, reason="weasyprint not installed")
def test_generate_pdf_creates_file(sample_events, location):
    generator = ReportGenerator(location)
    report_events = [event for event in sample_events if not event.is_false_pos]
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "report.pdf"
        generator.generate_pdf(
            events=report_events,
            start_date=datetime(2024, 1, 15),
            end_date=datetime(2024, 1, 15, 23, 59, 59),
            output_path=pdf_path,
        )
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 0


@pytest.mark.skipif(not WEASYPRINT_AVAILABLE, reason="weasyprint not installed")
def test_generate_zip_excludes_false_positive_clip(sample_events, location):
    generator = ReportGenerator(location)
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir) / "data"
        output_path = Path(tmpdir) / "report.zip"
        valid_clip = data_dir / "clips" / "2024-01-15" / "10-30-00_000.wav"
        false_clip = data_dir / "clips" / "2024-01-15" / "false.wav"
        valid_clip.parent.mkdir(parents=True, exist_ok=True)
        valid_clip.write_bytes(b"valid")
        false_clip.write_bytes(b"false")

        generator.generate_zip(
            events=sample_events,
            start_date=datetime(2024, 1, 15),
            end_date=datetime(2024, 1, 15, 23, 59, 59),
            data_dir=data_dir,
            output_path=output_path,
        )

        with zipfile.ZipFile(output_path) as zf:
            names = set(zf.namelist())
            csv_text = zf.read("events.csv").decode()

        assert "events.csv" in names
        assert "clips/2024-01-15/10-30-00_000.wav" in names
        assert "clips/2024-01-15/false.wav" not in names
        assert "Clip Hash" in csv_text
        assert "abc123def4567890fullhash" in csv_text
        assert "falsehash" not in csv_text
