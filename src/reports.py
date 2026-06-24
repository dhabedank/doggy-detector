"""PDF report and ZIP bundle generation for bark detection events."""

from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime
from html import escape
from io import StringIO
from pathlib import Path
from typing import List
import zipfile

from src.config import Config, LocationConfig
from src.storage import Event

try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False


def generate_pdf_report(
    events: List[Event],
    config: Config,
    start_date: datetime,
    end_date: datetime,
) -> bytes:
    """Generate a PDF report and return as bytes."""
    if not WEASYPRINT_AVAILABLE:
        raise RuntimeError("weasyprint not installed")

    generator = ReportGenerator(config.location)
    html_content = generator.generate_html(events, start_date, end_date)
    return HTML(string=html_content).write_pdf()


def generate_events_csv(events: List[Event]) -> str:
    """Generate CSV event data for report bundles and direct exports."""
    output = StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "ID", "Started At", "Ended At", "Duration (sec)",
        "Peak Score", "Avg Score", "Detection Threshold", "Peak Audio Level", "Avg Audio Level",
        "Direction", "Direction Score",
        "Clip Path", "Clip Hash", "False Positive", "False Pos Reason",
        "Weather Temp (F)", "Weather Wind (mph)", "Weather Conditions",
    ])

    for event in events:
        writer.writerow([
            event.id,
            event.started_at.isoformat(),
            event.ended_at.isoformat(),
            round(event.duration_sec, 2),
            round(event.peak_score, 3),
            round(event.avg_score, 3),
            round(event.detection_threshold, 3) if event.detection_threshold is not None else "",
            round(event.peak_audio_level, 3) if event.peak_audio_level is not None else "",
            round(event.avg_audio_level, 3) if event.avg_audio_level is not None else "",
            event.direction or "",
            round(event.direction_score, 3) if event.direction_score is not None else "",
            event.clip_path or "",
            event.clip_hash or "",
            event.is_false_pos,
            event.false_pos_reason or "",
            event.weather_temp_f if event.weather_temp_f is not None else "",
            event.weather_wind_mph if event.weather_wind_mph is not None else "",
            event.weather_conditions or "",
        ])

    return output.getvalue()


class ReportGenerator:
    """Generate HTML and PDF reports for bark detection events."""

    def __init__(self, location: LocationConfig):
        self.location = location

    def generate_html(
        self,
        events: List[Event],
        start_date: datetime,
        end_date: datetime,
    ) -> str:
        """Generate a landscape, print-dense HTML report."""
        stats = _build_stats(events)
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        period = f"{start_date:%Y-%m-%d} to {end_date:%Y-%m-%d}"
        location = escape(self.location.address or "Not specified")
        coordinates = _format_coordinates(self.location)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Doggy Detector Report</title>
    <style>
        @page {{
            size: Letter landscape;
            margin: 0.35in;
            @bottom-left {{
                content: "Doggy Detector evidence report";
                color: #6b7280;
                font-size: 7.5pt;
            }}
            @bottom-right {{
                content: "Page " counter(page) " of " counter(pages);
                color: #6b7280;
                font-size: 7.5pt;
            }}
        }}
        * {{
            box-sizing: border-box;
        }}
        body {{
            margin: 0;
            color: #111827;
            font-family: "Liberation Sans", "Helvetica Neue", Arial, sans-serif;
            font-size: 8.7pt;
            line-height: 1.25;
        }}
        .report-shell {{
            width: 100%;
        }}
        .topbar {{
            align-items: start;
            border-bottom: 1.5pt solid #111827;
            display: grid;
            gap: 0.2in;
            grid-template-columns: 1.2fr 1fr;
            padding-bottom: 0.12in;
        }}
        .kicker {{
            color: #6b7280;
            font-size: 7pt;
            font-weight: 700;
            letter-spacing: 0.08em;
            margin: 0 0 0.03in;
            text-transform: uppercase;
        }}
        h1 {{
            font-size: 20pt;
            letter-spacing: 0;
            line-height: 1;
            margin: 0;
        }}
        h2 {{
            color: #111827;
            font-size: 9.5pt;
            letter-spacing: 0;
            margin: 0 0 0.06in;
        }}
        .meta-grid {{
            border-left: 1pt solid #d1d5db;
            display: grid;
            gap: 0.03in 0.1in;
            grid-template-columns: 0.8in 1fr;
            padding-left: 0.14in;
        }}
        .meta-grid dt {{
            color: #6b7280;
            font-size: 7pt;
            font-weight: 700;
            margin: 0;
            text-transform: uppercase;
        }}
        .meta-grid dd {{
            margin: 0;
            min-width: 0;
            overflow-wrap: anywhere;
        }}
        .summary-grid {{
            display: grid;
            gap: 0.08in;
            grid-template-columns: repeat(5, 1fr);
            margin: 0.13in 0 0.1in;
        }}
        .metric {{
            border: 1pt solid #d1d5db;
            min-height: 0.46in;
            padding: 0.06in 0.07in;
        }}
        .metric-label {{
            color: #6b7280;
            display: block;
            font-size: 6.8pt;
            font-weight: 700;
            text-transform: uppercase;
        }}
        .metric-value {{
            display: block;
            font-size: 13pt;
            font-weight: 800;
            margin-top: 0.02in;
        }}
        .context-grid {{
            display: grid;
            gap: 0.08in;
            grid-template-columns: 1fr 1fr;
            margin-bottom: 0.11in;
        }}
        .panel {{
            border: 1pt solid #d1d5db;
            padding: 0.08in;
        }}
        .report-key {{
            border: 1pt solid #d1d5db;
            margin-bottom: 0.11in;
            padding: 0.08in;
        }}
        .key-grid {{
            display: grid;
            gap: 0.07in;
            grid-template-columns: repeat(4, 1fr);
        }}
        .key-label {{
            color: #111827;
            display: block;
            font-size: 7.2pt;
            font-weight: 800;
            margin-bottom: 0.02in;
            text-transform: uppercase;
        }}
        .key-copy {{
            color: #4b5563;
            font-size: 7.2pt;
            margin: 0;
        }}
        .direction-grid {{
            display: grid;
            gap: 0.05in;
            grid-template-columns: repeat(4, 1fr);
        }}
        .direction-card {{
            border-left: 3pt solid #9ca3af;
            padding-left: 0.06in;
        }}
        .direction-card.left {{
            border-color: #2563eb;
        }}
        .direction-card.right {{
            border-color: #dc2626;
        }}
        .direction-card.center {{
            border-color: #059669;
        }}
        .direction-label {{
            color: #4b5563;
            display: block;
            font-size: 7pt;
            font-weight: 700;
            text-transform: uppercase;
        }}
        .direction-value {{
            font-size: 12pt;
            font-weight: 800;
        }}
        .direction-share {{
            color: #6b7280;
            font-size: 7pt;
        }}
        .hour-grid {{
            display: grid;
            gap: 0.025in;
            grid-template-columns: repeat(8, 1fr);
        }}
        .hour-cell {{
            border: 0.5pt solid #e5e7eb;
            min-height: 0.24in;
            padding: 0.025in 0.04in;
        }}
        .hour-label {{
            color: #6b7280;
            display: block;
            font-size: 6.5pt;
        }}
        .hour-count {{
            font-size: 8.5pt;
            font-weight: 800;
        }}
        .incident-heading {{
            align-items: end;
            display: flex;
            justify-content: space-between;
            margin: 0 0 0.04in;
        }}
        .incident-heading p {{
            color: #6b7280;
            font-size: 7pt;
            margin: 0;
        }}
        table.incident-log {{
            border-collapse: collapse;
            table-layout: fixed;
            width: 100%;
        }}
        .incident-log th {{
            background: #111827;
            border: 0.5pt solid #111827;
            color: white;
            font-size: 7pt;
            line-height: 1;
            padding: 0.045in 0.04in;
            text-align: left;
            text-transform: uppercase;
        }}
        .incident-log td {{
            border: 0.5pt solid #d1d5db;
            font-size: 7.4pt;
            line-height: 1.18;
            padding: 0.04in;
            vertical-align: top;
        }}
        .incident-log tbody tr:nth-child(even) {{
            background: #f9fafb;
        }}
        .col-start {{
            width: 13%;
        }}
        .col-duration {{
            width: 6%;
        }}
        .col-score {{
            width: 8%;
        }}
        .col-direction {{
            width: 9%;
        }}
        .col-weather {{
            width: 17%;
        }}
        .col-clip {{
            width: 25%;
        }}
        .col-hash {{
            width: 12%;
        }}
        .num {{
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
        }}
        .muted {{
            color: #6b7280;
        }}
        .wrap-anywhere {{
            overflow-wrap: anywhere;
            word-break: break-word;
        }}
        .empty-row {{
            color: #6b7280;
            text-align: center;
        }}
        .appendix-page {{
            break-before: page;
            font-size: 8.4pt;
        }}
        .appendix-page h2 {{
            border-bottom: 1.5pt solid #111827;
            font-size: 14pt;
            margin-bottom: 0.12in;
            padding-bottom: 0.06in;
        }}
        .appendix-grid {{
            display: grid;
            gap: 0.12in;
            grid-template-columns: 1fr 1fr;
        }}
        .appendix-block {{
            border: 1pt solid #d1d5db;
            padding: 0.11in;
        }}
        .appendix-block h3 {{
            font-size: 9pt;
            margin: 0 0 0.05in;
        }}
        .appendix-block p,
        .appendix-block li {{
            color: #374151;
            margin: 0 0 0.05in;
        }}
        .appendix-block ul {{
            margin: 0;
            padding-left: 0.16in;
        }}
    </style>
</head>
<body>
    <main class="report-shell">
        <header class="topbar">
            <div>
                <p class="kicker">Bark Evidence Report</p>
                <h1>Doggy Detector</h1>
            </div>
            <dl class="meta-grid">
                <dt>Location</dt><dd>{location}</dd>
                <dt>Coordinates</dt><dd>{coordinates}</dd>
                <dt>Period</dt><dd>{period}</dd>
                <dt>Generated</dt><dd>{generated_at}</dd>
            </dl>
        </header>

        <section class="summary-grid" aria-label="Summary statistics">
            <div class="metric"><span class="metric-label">Incidents</span><span class="metric-value">{stats["total_incidents"]}</span></div>
            <div class="metric"><span class="metric-label">Barking Time</span><span class="metric-value">{_format_duration(stats["total_duration"])}</span></div>
            <div class="metric"><span class="metric-label">Longest</span><span class="metric-value">{_format_duration(stats["longest_duration"])}</span></div>
            <div class="metric"><span class="metric-label">Avg Peak</span><span class="metric-value">{stats["avg_peak_score"]:.2f}</span></div>
            <div class="metric"><span class="metric-label">Avg Duration</span><span class="metric-value">{_format_duration(stats["avg_duration"])}</span></div>
        </section>

        <section class="context-grid">
            <div class="panel">
                <h2>Direction Breakdown</h2>
                <div class="direction-grid">
                    {_build_direction_cards(stats["direction_counts"], stats["total_incidents"])}
                </div>
            </div>
            <div class="panel">
                <h2>Hourly Activity</h2>
                <div class="hour-grid">
                    {_build_hour_cells(stats["hour_counts"])}
                </div>
            </div>
        </section>

        <section class="report-key">
            <h2>Report Key</h2>
            <div class="key-grid">
                <div>
                    <span class="key-label">Scores</span>
                    <p class="key-copy">Model scores run from 0.000 to 1.000. Higher values mean the audio window looked more like a dog bark to the detector.</p>
                </div>
                <div>
                    <span class="key-label">P / A / T / L</span>
                    <p class="key-copy">P is peak score, A is average score, T is the threshold in effect, and L is peak input level during the incident.</p>
                </div>
                <div>
                    <span class="key-label">Hash</span>
                    <p class="key-copy">The report shows the first 12 characters of each clip's SHA-256 hash. The CSV includes the full hash.</p>
                </div>
                <div>
                    <span class="key-label">False Positives</span>
                    <p class="key-copy">Incidents marked false positive in the dashboard are excluded from this PDF, CSV, and clip bundle.</p>
                </div>
            </div>
        </section>

        <section>
            <div class="incident-heading">
                <h2>Incident Log</h2>
                <p>Hash values are SHA-256 prefixes; full hashes are in the CSV.</p>
            </div>
            <table class="incident-log">
                <colgroup>
                    <col class="col-start">
                    <col class="col-duration">
                    <col class="col-score">
                    <col class="col-direction">
                    <col class="col-weather">
                    <col class="col-clip">
                    <col class="col-hash">
                </colgroup>
                <thead>
                    <tr>
                        <th>Start</th>
                        <th>Dur</th>
                        <th>Score</th>
                        <th>Direction</th>
                        <th>Weather</th>
                        <th>Clip</th>
                        <th>Hash</th>
                    </tr>
                </thead>
                <tbody>
                    {_build_event_rows(events)}
                </tbody>
            </table>
        </section>

        <section class="appendix-page">
            <h2>About This Evidence Package</h2>
            <div class="appendix-grid">
                <div class="appendix-block">
                    <h3>What the software does</h3>
                    <p>Doggy Detector monitors the configured microphone, analyzes rolling audio windows for bark-like sounds, and groups qualifying detections into incidents using the configured threshold, minimum detection count, silence gap, merge window, and pre-roll settings.</p>
                    <p>This report summarizes incidents saved during the selected date range. It does not make a legal conclusion; it packages the underlying audio and metadata so the results can be reviewed.</p>
                </div>
                <div class="appendix-block">
                    <h3>Technology used</h3>
                    <ul>
                        <li>Audio classification is performed locally with the YAMNet TensorFlow model.</li>
                        <li>Event records and dashboard settings are stored in SQLite.</li>
                        <li>Saved clips are WAV audio files from the monitoring microphone.</li>
                        <li>Each saved clip receives a SHA-256 fingerprint when written.</li>
                    </ul>
                </div>
                <div class="appendix-block">
                    <h3>Why the results are auditable</h3>
                    <ul>
                        <li>Each incident includes a start time, duration, model scores, threshold used, and clip reference.</li>
                        <li>Calibration fields show both detector confidence and input audio level at the time of detection.</li>
                        <li>The CSV contains the detailed event table, including the full clip hash for comparison.</li>
                        <li>The ZIP includes the PDF, CSV, and referenced clips for non-false-positive incidents.</li>
                    </ul>
                </div>
                <div class="appendix-block">
                    <h3>How to review the package</h3>
                    <ul>
                        <li>Read the summary and incident log to identify dates, times, duration, scores, direction, and weather context.</li>
                        <li>Open the referenced WAV clips to hear the source audio for each listed incident.</li>
                        <li>Use the CSV for full precision values, full clip hashes, and spreadsheet review.</li>
                        <li>Compare a clip's SHA-256 hash to the CSV value to confirm the audio file matches the exported record.</li>
                    </ul>
                </div>
            </div>
        </section>
    </main>
</body>
</html>"""

    def generate_pdf(
        self,
        events: List[Event],
        start_date: datetime,
        end_date: datetime,
        output_path: Path,
    ) -> None:
        """Generate a PDF report from bark detection events."""
        if not WEASYPRINT_AVAILABLE:
            raise RuntimeError("weasyprint is not installed. Install it with: pip install weasyprint")

        HTML(string=self.generate_html(events, start_date, end_date)).write_pdf(output_path)

    def generate_zip(
        self,
        events: List[Event],
        start_date: datetime,
        end_date: datetime,
        data_dir: Path,
        output_path: Path,
    ) -> None:
        """Generate a ZIP bundle with PDF report and audio clips."""
        import tempfile

        report_events = [event for event in events if not event.is_false_pos]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            pdf_path = tmpdir_path / "report.pdf"

            self.generate_pdf(report_events, start_date, end_date, pdf_path)

            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(pdf_path, arcname="report.pdf")
                zf.writestr("events.csv", generate_events_csv(report_events))
                for event in report_events:
                    if not event.clip_path:
                        continue
                    clip_full_path = (data_dir / event.clip_path).resolve()
                    try:
                        clip_full_path.relative_to(data_dir.resolve())
                    except ValueError:
                        continue
                    if clip_full_path.exists():
                        zf.write(clip_full_path, arcname=event.clip_path)


def _build_stats(events: List[Event]) -> dict:
    total_incidents = len(events)
    total_duration = sum(event.duration_sec for event in events)
    return {
        "total_incidents": total_incidents,
        "total_duration": total_duration,
        "longest_duration": max((event.duration_sec for event in events), default=0),
        "avg_peak_score": sum(event.peak_score for event in events) / total_incidents if total_incidents else 0,
        "avg_duration": total_duration / total_incidents if total_incidents else 0,
        "direction_counts": _direction_counts(events),
        "hour_counts": Counter(event.started_at.hour for event in events),
    }


def _direction_counts(events: List[Event]) -> Counter:
    counts = Counter()
    for event in events:
        direction = event.direction if event.direction in {"left", "right", "center"} else "unknown"
        counts[direction] += 1
    return counts


def _build_direction_cards(counts: Counter, total: int) -> str:
    labels = (
        ("left", "Left"),
        ("right", "Right"),
        ("center", "Center"),
        ("unknown", "Unknown"),
    )
    cards = []
    for key, label in labels:
        count = counts.get(key, 0)
        share = (count / total * 100) if total else 0
        cards.append(
            f"""
            <div class="direction-card {key}">
                <span class="direction-label">{label}</span>
                <span class="direction-value">{count}</span>
                <span class="direction-share">{share:.0f}% of incidents</span>
            </div>
            """
        )
    return "".join(cards)


def _build_hour_cells(hour_counts: Counter) -> str:
    if not hour_counts:
        return '<div class="hour-cell"><span class="hour-count">No incidents</span></div>'

    cells = []
    for hour in range(24):
        count = hour_counts.get(hour, 0)
        if count == 0:
            continue
        cells.append(
            f"""
            <div class="hour-cell">
                <span class="hour-label">{hour:02d}:00</span>
                <span class="hour-count">{count}</span>
            </div>
            """
        )
    return "".join(cells)


def _build_event_rows(events: List[Event]) -> str:
    if not events:
        return '<tr><td class="empty-row" colspan="7">No incidents in this report period.</td></tr>'

    rows = []
    for event in events:
        rows.append(
            f"""
            <tr>
                <td class="num">{event.started_at:%Y-%m-%d}<br><span class="muted">{event.started_at:%H:%M:%S}</span></td>
                <td class="num">{_format_duration(event.duration_sec)}</td>
                <td class="num">{_format_score_calibration(event)}</td>
                <td>{_format_direction(event)}</td>
                <td class="wrap-anywhere">{_format_weather(event)}</td>
                <td class="wrap-anywhere">{_format_clip_name(event.clip_path)}</td>
                <td class="wrap-anywhere num">{_format_hash(event.clip_hash)}</td>
            </tr>
            """
        )
    return "".join(rows)


def _format_coordinates(location: LocationConfig) -> str:
    if location.lat is None or location.lon is None:
        return "Not specified"
    return f"{location.lat:.6f}, {location.lon:.6f}"


def _format_duration(seconds: float) -> str:
    if seconds >= 3600:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"
    if seconds >= 60:
        minutes = int(seconds // 60)
        remaining = int(seconds % 60)
        return f"{minutes}m {remaining}s"
    return f"{seconds:.1f}s"


def _format_direction(event: Event) -> str:
    direction = event.direction if event.direction in {"left", "right", "center"} else "unknown"
    label = direction.capitalize()
    if event.direction_score is None:
        return label
    return f"{label}<br><span class=\"muted num\">{event.direction_score:.2f}</span>"


def _format_score_calibration(event: Event) -> str:
    rows = [
        f"P {event.peak_score:.2f}",
        f"<span class=\"muted\">A {event.avg_score:.2f}</span>",
    ]
    if event.detection_threshold is not None:
        rows.append(f"<span class=\"muted\">T {event.detection_threshold:.3f}</span>")
    if event.peak_audio_level is not None:
        rows.append(f"<span class=\"muted\">L {event.peak_audio_level:.2f}</span>")
    return "<br>".join(rows)


def _format_weather(event: Event) -> str:
    parts = []
    if event.weather_temp_f is not None:
        parts.append(f"{event.weather_temp_f:.0f} F")
    if event.weather_wind_mph is not None:
        parts.append(f"{event.weather_wind_mph:.0f} mph wind")
    if event.weather_conditions:
        parts.append(escape(event.weather_conditions))
    return " / ".join(parts) if parts else "N/A"


def _format_clip_name(clip_path: str | None) -> str:
    if not clip_path:
        return "N/A"
    return escape(Path(clip_path).name)


def _format_hash(clip_hash: str | None) -> str:
    if not clip_hash:
        return "N/A"
    return escape(clip_hash[:12])
