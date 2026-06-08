"""PDF report and ZIP bundle generation for bark detection events."""

from pathlib import Path
from datetime import datetime
from typing import List, Optional
import zipfile
import io

from src.config import Config, LocationConfig
from src.storage import Event

# Try to import weasyprint for PDF generation
try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False


def generate_pdf_report(
    events: List[Event],
    config: Config,
    start_date: datetime,
    end_date: datetime,
) -> bytes:
    """Generate a PDF report and return as bytes.

    Args:
        events: List of events to include
        config: App configuration (for location info)
        start_date: Report start date
        end_date: Report end date

    Returns:
        PDF file contents as bytes
    """
    if not WEASYPRINT_AVAILABLE:
        raise RuntimeError("weasyprint not installed")

    generator = ReportGenerator(config.location)
    html_content = generator.generate_html(events, start_date, end_date)

    # Generate PDF to bytes
    pdf_bytes = HTML(string=html_content).write_pdf()
    return pdf_bytes


class ReportGenerator:
    """Generate HTML and PDF reports for bark detection events."""

    def __init__(self, location: LocationConfig):
        """Initialize the report generator.

        Args:
            location: LocationConfig with address and coordinates
        """
        self.location = location

    def generate_html(
        self,
        events: List[Event],
        start_date: datetime,
        end_date: datetime,
    ) -> str:
        """Generate an HTML report of bark detection events.

        Args:
            events: List of Event objects to include in the report
            start_date: Report period start date
            end_date: Report period end date

        Returns:
            HTML string representing the report
        """
        # Calculate summary statistics
        total_incidents = len(events)
        left_count = sum(1 for e in events if e.direction == "left")
        right_count = sum(1 for e in events if e.direction == "right")
        center_count = sum(1 for e in events if e.direction == "center")
        unknown_count = sum(1 for e in events if e.direction is None or e.direction not in ["left", "right", "center"])

        total_barks = sum(e.bark_count for e in events)
        avg_peak_score = sum(e.peak_score for e in events) / total_incidents if total_incidents > 0 else 0
        avg_duration = sum(e.duration_sec for e in events) / total_incidents if total_incidents > 0 else 0

        # Build event rows
        event_rows = ""
        for event in events:
            clip_name = Path(event.clip_path).name if event.clip_path else "N/A"
            clip_hash_short = event.clip_hash[:8] if event.clip_hash else "N/A"
            weather = f"{event.weather_temp_f}°F, {event.weather_wind_mph} mph, {event.weather_conditions}" if event.weather_temp_f else "N/A"
            direction_display = event.direction.capitalize() if event.direction else "Unknown"
            direction_score_display = f"{event.direction_score:.2f}" if event.direction_score else "N/A"

            event_rows += f"""
            <tr>
                <td>{event.started_at.strftime("%Y-%m-%d %H:%M:%S")}</td>
                <td>{event.duration_sec:.1f}s</td>
                <td>{event.bark_count}</td>
                <td>{event.peak_score:.2f}</td>
                <td>{event.avg_score:.2f}</td>
                <td>{direction_display}</td>
                <td>{direction_score_display}</td>
                <td>{clip_name}</td>
                <td>{clip_hash_short}</td>
                <td>{weather}</td>
            </tr>
            """

        # Build direction summary
        direction_summary = ""
        if left_count > 0:
            direction_summary += f"Left direction: {left_count}\n"
        if right_count > 0:
            direction_summary += f"Right direction: {right_count}\n"
        if center_count > 0:
            direction_summary += f"Center direction: {center_count}\n"
        if unknown_count > 0:
            direction_summary += f"Unknown direction: {unknown_count}\n"

        # Generate timestamp
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Build HTML document
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Doggy Detector Report</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            color: #333;
        }}
        h1 {{
            color: #1a3a52;
            text-align: center;
            border-bottom: 3px solid #1a3a52;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #1a3a52;
            margin-top: 25px;
            border-left: 4px solid #1a3a52;
            padding-left: 10px;
        }}
        .report-header {{
            background-color: #f5f5f5;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }}
        .report-header p {{
            margin: 5px 0;
        }}
        .summary {{
            background-color: #e8f4f8;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }}
        .summary p {{
            margin: 5px 0;
            font-size: 14px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
        }}
        th {{
            background-color: #1a3a52;
            color: white;
            padding: 10px;
            text-align: left;
            font-size: 13px;
        }}
        td {{
            border: 1px solid #ddd;
            padding: 8px;
            font-size: 12px;
        }}
        tr:nth-child(even) {{
            background-color: #f9f9f9;
        }}
        .footer {{
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            font-size: 12px;
            color: #666;
        }}
    </style>
</head>
<body>
    <h1>DOGGY DETECTOR REPORT</h1>

    <div class="report-header">
        <h2>Report Information</h2>
        <p><strong>Location:</strong> {self.location.address or 'Not specified'}</p>
        <p><strong>Coordinates:</strong> {f"{self.location.lat:.4f}, {self.location.lon:.4f}" if self.location.lat and self.location.lon else "Not specified"}</p>
        <p><strong>Report Period:</strong> {start_date.strftime("%Y-%m-%d")} to {end_date.strftime("%Y-%m-%d")}</p>
        <p><strong>Generated:</strong> {generated_at}</p>
    </div>

    <div class="summary">
        <h2>Summary Statistics</h2>
        <p><strong>Total incidents: {total_incidents}</strong></p>
        <p><strong>Total barks detected: {total_barks}</strong></p>
        <p><strong>Average peak confidence:</strong> {avg_peak_score:.2f}</p>
        <p><strong>Average incident duration:</strong> {avg_duration:.1f} seconds</p>
        <p><strong>Direction breakdown:</strong></p>
        <pre style="margin: 5px 0; padding-left: 20px;">{direction_summary.strip()}</pre>
    </div>

    <h2>Incident Log</h2>
    <table>
        <thead>
            <tr>
                <th>Timestamp</th>
                <th>Duration</th>
                <th>Barks</th>
                <th>Peak Score</th>
                <th>Avg Score</th>
                <th>Direction</th>
                <th>Dir Score</th>
                <th>Clip Name</th>
                <th>Hash</th>
                <th>Weather</th>
            </tr>
        </thead>
        <tbody>
            {event_rows}
        </tbody>
    </table>

    <div class="footer">
        <p>This report was automatically generated by the Doggy Detector system.</p>
    </div>
</body>
</html>"""

        return html

    def generate_pdf(
        self,
        events: List[Event],
        start_date: datetime,
        end_date: datetime,
        output_path: Path,
    ) -> None:
        """Generate a PDF report from bark detection events.

        Args:
            events: List of Event objects to include in the report
            start_date: Report period start date
            end_date: Report period end date
            output_path: Path where the PDF should be saved

        Raises:
            RuntimeError: If weasyprint is not installed
        """
        if not WEASYPRINT_AVAILABLE:
            raise RuntimeError("weasyprint is not installed. Install it with: pip install weasyprint")

        # Generate HTML
        html_content = self.generate_html(events, start_date, end_date)

        # Convert to PDF using weasyprint
        HTML(string=html_content).write_pdf(output_path)

    def generate_zip(
        self,
        events: List[Event],
        start_date: datetime,
        end_date: datetime,
        data_dir: Path,
        output_path: Path,
    ) -> None:
        """Generate a ZIP bundle with PDF report and audio clips.

        Args:
            events: List of Event objects to include in the report
            start_date: Report period start date
            end_date: Report period end date
            data_dir: Base data directory where clips are stored
            output_path: Path where the ZIP file should be saved
        """
        import tempfile

        # Create a temporary directory for the PDF
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            pdf_path = tmpdir_path / "report.pdf"

            # Generate PDF
            self.generate_pdf(events, start_date, end_date, pdf_path)

            # Create ZIP file
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                # Add the PDF
                zf.write(pdf_path, arcname="report.pdf")

                # Add audio clips
                for event in events:
                    if event.clip_path:
                        clip_full_path = data_dir / event.clip_path
                        if clip_full_path.exists():
                            zf.write(clip_full_path, arcname=event.clip_path)
