"""SQLite storage and clip management."""

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List
import sqlite3
import hashlib


@dataclass
class Event:
    started_at: datetime
    ended_at: datetime
    duration_sec: float
    bark_count: int
    peak_score: float
    avg_score: float
    detection_threshold: Optional[float] = None
    peak_audio_level: Optional[float] = None
    avg_audio_level: Optional[float] = None
    direction: Optional[str] = None
    direction_score: Optional[float] = None
    clip_path: Optional[str] = None
    clip_hash: Optional[str] = None
    is_false_pos: bool = False
    false_pos_reason: Optional[str] = None
    weather_temp_f: Optional[float] = None
    weather_wind_mph: Optional[float] = None
    weather_conditions: Optional[str] = None
    id: Optional[int] = None
    created_at: Optional[datetime] = None


class Storage:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "clips").mkdir(exist_ok=True)
        (self.data_dir / "reports").mkdir(exist_ok=True)

        self.db_path = self.data_dir / "events.sqlite"
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at         TEXT NOT NULL,
                ended_at           TEXT NOT NULL,
                duration_sec       REAL NOT NULL,
                bark_count         INTEGER NOT NULL,
                peak_score         REAL NOT NULL,
                avg_score          REAL NOT NULL,
                detection_threshold REAL,
                peak_audio_level   REAL,
                avg_audio_level    REAL,
                direction          TEXT,
                direction_score    REAL,
                clip_path          TEXT,
                clip_hash          TEXT,
                is_false_pos       INTEGER DEFAULT 0,
                false_pos_reason   TEXT,
                weather_temp_f     REAL,
                weather_wind_mph   REAL,
                weather_conditions TEXT,
                created_at         TEXT NOT NULL
            )
        """)
        self._ensure_event_columns(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_started_at ON events(started_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_is_false_pos ON events(is_false_pos)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key        TEXT PRIMARY KEY,
                value      TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def _ensure_event_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
        migrations = {
            "detection_threshold": "ALTER TABLE events ADD COLUMN detection_threshold REAL",
            "peak_audio_level": "ALTER TABLE events ADD COLUMN peak_audio_level REAL",
            "avg_audio_level": "ALTER TABLE events ADD COLUMN avg_audio_level REAL",
        }
        for column, statement in migrations.items():
            if column not in columns:
                conn.execute(statement)

    def save_event(self, event: Event) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            """
            INSERT INTO events (
                started_at, ended_at, duration_sec, bark_count, peak_score, avg_score,
                detection_threshold, peak_audio_level, avg_audio_level,
                direction, direction_score, clip_path, clip_hash, is_false_pos,
                false_pos_reason, weather_temp_f, weather_wind_mph, weather_conditions,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.started_at.isoformat(),
                event.ended_at.isoformat(),
                event.duration_sec,
                event.bark_count,
                event.peak_score,
                event.avg_score,
                event.detection_threshold,
                event.peak_audio_level,
                event.avg_audio_level,
                event.direction,
                event.direction_score,
                event.clip_path,
                event.clip_hash,
                1 if event.is_false_pos else 0,
                event.false_pos_reason,
                event.weather_temp_f,
                event.weather_wind_mph,
                event.weather_conditions,
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        event_id = cursor.lastrowid
        conn.close()
        return event_id

    def get_event(self, event_id: int) -> Optional[Event]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,))
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        return self._row_to_event(row)

    def list_events(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        include_false_pos: bool = True,
        only_false_pos: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Event]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        query = "SELECT * FROM events WHERE 1=1"
        params = []

        if start_date:
            query += " AND started_at >= ?"
            params.append(start_date.isoformat())

        if end_date:
            query += " AND started_at <= ?"
            params.append(end_date.isoformat())

        if only_false_pos:
            query += " AND is_false_pos = 1"
        elif not include_false_pos:
            query += " AND is_false_pos = 0"

        query += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_event(row) for row in rows]

    def count_events(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        include_false_pos: bool = True,
        only_false_pos: bool = False,
    ) -> int:
        conn = sqlite3.connect(self.db_path)

        query = "SELECT COUNT(*) FROM events WHERE 1=1"
        params = []

        if start_date:
            query += " AND started_at >= ?"
            params.append(start_date.isoformat())

        if end_date:
            query += " AND started_at <= ?"
            params.append(end_date.isoformat())

        if only_false_pos:
            query += " AND is_false_pos = 1"
        elif not include_false_pos:
            query += " AND is_false_pos = 0"

        cursor = conn.execute(query, params)
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def summarize_events(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        include_false_pos: bool = False,
    ) -> dict[str, float | int]:
        """Summarize events for dashboard cards."""
        conn = sqlite3.connect(self.db_path)

        query = """
            SELECT
                COUNT(*) AS incident_count,
                COALESCE(SUM(duration_sec), 0) AS total_duration_sec,
                COALESCE(MAX(duration_sec), 0) AS longest_duration_sec,
                COALESCE(MAX(peak_score), 0) AS peak_score
            FROM events
            WHERE 1=1
        """
        params = []

        if start_date:
            query += " AND started_at >= ?"
            params.append(start_date.isoformat())

        if end_date:
            query += " AND started_at <= ?"
            params.append(end_date.isoformat())

        if not include_false_pos:
            query += " AND is_false_pos = 0"

        row = conn.execute(query, params).fetchone()
        conn.close()

        return {
            "incident_count": int(row[0]),
            "total_duration_sec": float(row[1]),
            "longest_duration_sec": float(row[2]),
            "peak_score": float(row[3]),
        }

    def flag_false_positive(self, event_id: int, reason: Optional[str] = None):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE events SET is_false_pos = 1, false_pos_reason = ? WHERE id = ?",
            (reason, event_id),
        )
        conn.commit()
        conn.close()

    def unflag_false_positive(self, event_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE events SET is_false_pos = 0, false_pos_reason = NULL WHERE id = ?",
            (event_id,),
        )
        conn.commit()
        conn.close()

    def delete_event(self, event_id: int, delete_clip: bool = True) -> Optional[Event]:
        """Delete an event row and optionally its referenced clip."""
        event = self.get_event(event_id)
        if event is None:
            return None

        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        conn.commit()
        conn.close()

        if delete_clip and event.clip_path:
            self._delete_relative_clip(event.clip_path)

        return event

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        return Event(
            id=row["id"],
            started_at=datetime.fromisoformat(row["started_at"]),
            ended_at=datetime.fromisoformat(row["ended_at"]),
            duration_sec=row["duration_sec"],
            bark_count=row["bark_count"],
            peak_score=row["peak_score"],
            avg_score=row["avg_score"],
            detection_threshold=row["detection_threshold"],
            peak_audio_level=row["peak_audio_level"],
            avg_audio_level=row["avg_audio_level"],
            direction=row["direction"],
            direction_score=row["direction_score"],
            clip_path=row["clip_path"],
            clip_hash=row["clip_hash"],
            is_false_pos=bool(row["is_false_pos"]),
            false_pos_reason=row["false_pos_reason"],
            weather_temp_f=row["weather_temp_f"],
            weather_wind_mph=row["weather_wind_mph"],
            weather_conditions=row["weather_conditions"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        )

    def save_clip(self, audio_data: bytes, timestamp: datetime) -> tuple[str, str]:
        """Save audio clip and return (relative_path, sha256_hash)."""
        date_dir = self.data_dir / "clips" / timestamp.strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        filename_stem = timestamp.strftime("%H-%M-%S") + f"_{timestamp.microsecond // 1000:03d}"
        clip_path = None
        filename = ""

        for suffix in [""] + [f"_{i:03d}" for i in range(1, 1000)]:
            filename = f"{filename_stem}{suffix}.wav"
            candidate_path = date_dir / filename
            try:
                with candidate_path.open("xb") as f:
                    f.write(audio_data)
                clip_path = candidate_path
                break
            except FileExistsError:
                continue

        if clip_path is None:
            raise FileExistsError(f"Could not create unique clip filename for {timestamp.isoformat()}")

        relative_path = f"clips/{timestamp.strftime('%Y-%m-%d')}/{filename}"

        clip_hash = hashlib.sha256(audio_data).hexdigest()

        return relative_path, clip_hash

    def _delete_relative_clip(self, relative_clip_path: str) -> bool:
        clip_path = (self.data_dir / relative_clip_path).resolve()
        try:
            clip_path.relative_to(self.data_dir.resolve())
        except ValueError:
            return False

        try:
            if clip_path.exists() and clip_path.is_file():
                clip_path.unlink()
                self._remove_empty_clip_parent(clip_path.parent)
                return True
        except OSError:
            return False

        return False

    def _remove_empty_clip_parent(self, directory: Path) -> None:
        clips_root = (self.data_dir / "clips").resolve()
        try:
            directory.resolve().relative_to(clips_root)
            directory.rmdir()
        except (OSError, ValueError):
            pass

    def save_event_with_retry(self, event: Event, attempts: int = 3, delay_sec: float = 0.05) -> int:
        """Save an event, retrying transient SQLite failures."""
        last_error: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                return self.save_event(event)
            except sqlite3.Error as exc:
                last_error = exc
                if attempt < attempts - 1:
                    time.sleep(delay_sec)

        assert last_error is not None
        raise last_error

    def save_pending_event(self, event: Event, error: Exception) -> Path:
        """Write a small metadata file for manual recovery after DB failure."""
        pending_dir = self.data_dir / "pending_events"
        pending_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        pending_path = pending_dir / f"{timestamp}.json"

        data = asdict(event)
        for key in ("started_at", "ended_at", "created_at"):
            if isinstance(data.get(key), datetime):
                data[key] = data[key].isoformat()
        data["db_error"] = str(error)

        with pending_path.open("x") as f:
            json.dump(data, f, indent=2, sort_keys=True)

        return pending_path

    def prune_retention(self, retention_days: int, now: Optional[datetime] = None) -> dict[str, int]:
        """Delete old event rows and their referenced clips."""
        if retention_days <= 0:
            return {"events_deleted": 0, "clips_deleted": 0}

        cutoff = (now or datetime.now()) - timedelta(days=retention_days)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, clip_path FROM events WHERE started_at < ?",
            (cutoff.isoformat(),),
        ).fetchall()

        event_ids = [row["id"] for row in rows]
        clip_paths = [row["clip_path"] for row in rows if row["clip_path"]]

        if event_ids:
            placeholders = ",".join("?" for _ in event_ids)
            conn.execute(f"DELETE FROM events WHERE id IN ({placeholders})", event_ids)
            conn.commit()
        conn.close()

        clips_deleted = 0
        for relative_clip_path in clip_paths:
            if self._delete_relative_clip(relative_clip_path):
                clips_deleted += 1

        return {"events_deleted": len(event_ids), "clips_deleted": clips_deleted}
