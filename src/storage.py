"""SQLite storage and clip management."""

from dataclasses import dataclass, field
from datetime import datetime
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_started_at ON events(started_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_is_false_pos ON events(is_false_pos)")
        conn.commit()
        conn.close()

    def save_event(self, event: Event) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            """
            INSERT INTO events (
                started_at, ended_at, duration_sec, bark_count, peak_score, avg_score,
                direction, direction_score, clip_path, clip_hash, is_false_pos,
                false_pos_reason, weather_temp_f, weather_wind_mph, weather_conditions,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.started_at.isoformat(),
                event.ended_at.isoformat(),
                event.duration_sec,
                event.bark_count,
                event.peak_score,
                event.avg_score,
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

        if not include_false_pos:
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

        if not include_false_pos:
            query += " AND is_false_pos = 0"

        cursor = conn.execute(query, params)
        count = cursor.fetchone()[0]
        conn.close()
        return count

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

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        return Event(
            id=row["id"],
            started_at=datetime.fromisoformat(row["started_at"]),
            ended_at=datetime.fromisoformat(row["ended_at"]),
            duration_sec=row["duration_sec"],
            bark_count=row["bark_count"],
            peak_score=row["peak_score"],
            avg_score=row["avg_score"],
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

        filename = timestamp.strftime("%H-%M-%S") + f"_{timestamp.microsecond // 1000:03d}.wav"
        clip_path = date_dir / filename
        relative_path = f"clips/{timestamp.strftime('%Y-%m-%d')}/{filename}"

        clip_path.write_bytes(audio_data)

        clip_hash = hashlib.sha256(audio_data).hexdigest()

        return relative_path, clip_hash
