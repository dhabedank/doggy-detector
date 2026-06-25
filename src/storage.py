"""SQLite storage and clip management."""

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Any
import sqlite3
import hashlib
import struct


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
    bark_markers: list[dict[str, Any]] = field(default_factory=list)
    id: Optional[int] = None
    created_at: Optional[datetime] = None


@dataclass
class DeterrenceEvent:
    fired_at: datetime
    source: str
    mode: str
    profile: str
    status: str
    bark_score: Optional[float] = None
    audio_level: Optional[float] = None
    duration_sec: Optional[float] = None
    error: Optional[str] = None
    id: Optional[int] = None


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
                bark_markers       TEXT,
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deterrence_events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                fired_at     TEXT NOT NULL,
                source       TEXT NOT NULL,
                mode         TEXT NOT NULL,
                profile      TEXT NOT NULL,
                status       TEXT NOT NULL,
                bark_score   REAL,
                audio_level  REAL,
                duration_sec REAL,
                error        TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_deterrence_fired_at ON deterrence_events(fired_at)")
        conn.commit()
        conn.close()

    def _ensure_event_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
        migrations = {
            "detection_threshold": "ALTER TABLE events ADD COLUMN detection_threshold REAL",
            "peak_audio_level": "ALTER TABLE events ADD COLUMN peak_audio_level REAL",
            "avg_audio_level": "ALTER TABLE events ADD COLUMN avg_audio_level REAL",
            "bark_markers": "ALTER TABLE events ADD COLUMN bark_markers TEXT",
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
                bark_markers, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.started_at.isoformat(),
                event.ended_at.isoformat(),
                _required_float(event.duration_sec),
                _required_int(event.bark_count),
                _required_float(event.peak_score),
                _required_float(event.avg_score),
                _optional_float(event.detection_threshold),
                _optional_float(event.peak_audio_level),
                _optional_float(event.avg_audio_level),
                event.direction,
                _optional_float(event.direction_score),
                event.clip_path,
                event.clip_hash,
                1 if event.is_false_pos else 0,
                event.false_pos_reason,
                _optional_float(event.weather_temp_f),
                _optional_float(event.weather_wind_mph),
                event.weather_conditions,
                _encode_bark_markers(event.bark_markers),
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
        sort_by: str = "started_at",
        sort_order: str = "desc",
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

        sort_columns = {
            "started_at": "started_at",
            "duration_sec": "duration_sec",
            "peak_score": "peak_score",
            "direction": "direction",
        }
        sort_column = sort_columns.get(sort_by, "started_at")
        direction = "ASC" if sort_order.lower() == "asc" else "DESC"
        id_direction = "ASC" if direction == "ASC" else "DESC"
        query += f" ORDER BY {sort_column} {direction}, id {id_direction} LIMIT ? OFFSET ?"
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

    def save_deterrence_event(self, event: DeterrenceEvent) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            """
            INSERT INTO deterrence_events (
                fired_at, source, mode, profile, status, bark_score,
                audio_level, duration_sec, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.fired_at.isoformat(),
                event.source,
                event.mode,
                event.profile,
                event.status,
                _optional_float(event.bark_score),
                _optional_float(event.audio_level),
                _optional_float(event.duration_sec),
                event.error,
            ),
        )
        conn.commit()
        event_id = cursor.lastrowid
        conn.close()
        return event_id

    def list_deterrence_events(self, limit: int = 50, offset: int = 0) -> List[DeterrenceEvent]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM deterrence_events
            ORDER BY fired_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        conn.close()
        return [self._row_to_deterrence_event(row) for row in rows]

    def count_deterrence_events(
        self,
        start_at: Optional[datetime] = None,
        status: Optional[str] = None,
    ) -> int:
        conn = sqlite3.connect(self.db_path)
        query = "SELECT COUNT(*) FROM deterrence_events WHERE 1=1"
        params = []
        if start_at is not None:
            query += " AND fired_at >= ?"
            params.append(start_at.isoformat())
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        row = conn.execute(query, params).fetchone()
        conn.close()
        return int(row[0])

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
            id=_optional_int(row["id"]),
            started_at=datetime.fromisoformat(_required_text(row["started_at"])),
            ended_at=datetime.fromisoformat(_required_text(row["ended_at"])),
            duration_sec=_required_float(row["duration_sec"]),
            bark_count=_required_int(row["bark_count"]),
            peak_score=_required_float(row["peak_score"]),
            avg_score=_required_float(row["avg_score"]),
            detection_threshold=_optional_float(row["detection_threshold"]),
            peak_audio_level=_optional_float(row["peak_audio_level"]),
            avg_audio_level=_optional_float(row["avg_audio_level"]),
            direction=_optional_text(row["direction"]),
            direction_score=_optional_float(row["direction_score"]),
            clip_path=_optional_text(row["clip_path"]),
            clip_hash=_optional_text(row["clip_hash"]),
            is_false_pos=bool(_required_int(row["is_false_pos"])),
            false_pos_reason=_optional_text(row["false_pos_reason"]),
            weather_temp_f=_optional_float(row["weather_temp_f"]),
            weather_wind_mph=_optional_float(row["weather_wind_mph"]),
            weather_conditions=_optional_text(row["weather_conditions"]),
            bark_markers=_decode_bark_markers(
                row["bark_markers"] if "bark_markers" in row.keys() else None
            ),
            created_at=(
                datetime.fromisoformat(_required_text(row["created_at"]))
                if row["created_at"] else None
            ),
        )

    def _row_to_deterrence_event(self, row: sqlite3.Row) -> DeterrenceEvent:
        return DeterrenceEvent(
            id=_optional_int(row["id"]),
            fired_at=datetime.fromisoformat(_required_text(row["fired_at"])),
            source=_required_text(row["source"]),
            mode=_required_text(row["mode"]),
            profile=_required_text(row["profile"]),
            status=_required_text(row["status"]),
            bark_score=_optional_float(row["bark_score"]),
            audio_level=_optional_float(row["audio_level"]),
            duration_sec=_optional_float(row["duration_sec"]),
            error=_optional_text(row["error"]),
        )

    def save_clip(self, audio_data: bytes, timestamp: datetime) -> tuple[str, str]:
        """Save audio clip and return (relative_path, sha256_hash)."""
        clip_hash = hashlib.sha256(audio_data).hexdigest()
        for relative_path, clip_path in self._clip_path_candidates(timestamp):
            try:
                with clip_path.open("xb") as f:
                    f.write(audio_data)
                return relative_path, clip_hash
            except FileExistsError:
                continue
        raise FileExistsError(f"Could not create unique clip filename for {timestamp.isoformat()}")

    def save_clip_file(self, source_path: Path, timestamp: datetime) -> tuple[str, str]:
        """Stream a WAV clip from an existing file and return (relative_path, sha256_hash)."""
        for relative_path, clip_path in self._clip_path_candidates(timestamp):
            hasher = hashlib.sha256()
            try:
                with clip_path.open("xb") as target, source_path.open("rb") as source:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        hasher.update(chunk)
                        target.write(chunk)
                return relative_path, hasher.hexdigest()
            except FileExistsError:
                continue
            except Exception:
                try:
                    clip_path.unlink()
                except OSError:
                    pass
                raise
        raise FileExistsError(f"Could not create unique clip filename for {timestamp.isoformat()}")

    def _clip_path_candidates(self, timestamp: datetime):
        date_dir = self.data_dir / "clips" / timestamp.strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        filename_stem = timestamp.strftime("%H-%M-%S") + f"_{timestamp.microsecond // 1000:03d}"

        for suffix in [""] + [f"_{i:03d}" for i in range(1, 1000)]:
            filename = f"{filename_stem}{suffix}.wav"
            candidate_path = date_dir / filename
            relative_path = f"clips/{timestamp.strftime('%Y-%m-%d')}/{filename}"
            yield relative_path, candidate_path

    def resolve_clip_path(self, relative_clip_path: str) -> Optional[Path]:
        """Resolve a stored clip path only if it points to a WAV under clips/."""
        try:
            relative_path = Path(relative_clip_path)
        except TypeError:
            return None
        if relative_path.is_absolute():
            return None
        if len(relative_path.parts) < 3 or relative_path.parts[0] != "clips":
            return None
        if relative_path.suffix.lower() != ".wav":
            return None

        clip_path = (self.data_dir / relative_path).resolve()
        clips_root = (self.data_dir / "clips").resolve()
        try:
            clip_path.relative_to(clips_root)
        except ValueError:
            return None
        return clip_path

    def _delete_relative_clip(self, relative_clip_path: str) -> bool:
        clip_path = self.resolve_clip_path(relative_clip_path)
        if clip_path is None:
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


def _required_float(value) -> float:
    converted = _optional_float(value)
    if converted is None:
        raise ValueError("Expected numeric value, got None")
    return converted


def _optional_float(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        if len(raw) == 4:
            return float(struct.unpack("<f", raw)[0])
        if len(raw) == 8:
            return float(struct.unpack("<d", raw)[0])
        return float(raw.decode())
    if hasattr(value, "item"):
        value = value.item()
    return float(value)


def _required_int(value) -> int:
    converted = _optional_int(value)
    if converted is None:
        raise ValueError("Expected integer value, got None")
    return converted


def _optional_int(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        if len(raw) == 1:
            return int(raw[0])
        if len(raw) == 2:
            return int.from_bytes(raw, "little", signed=True)
        if len(raw) == 4:
            return int.from_bytes(raw, "little", signed=True)
        if len(raw) == 8:
            return int.from_bytes(raw, "little", signed=True)
        return int(raw.decode())
    if hasattr(value, "item"):
        value = value.item()
    return int(value)


def _required_text(value) -> str:
    converted = _optional_text(value)
    if converted is None:
        raise ValueError("Expected text value, got None")
    return converted


def _optional_text(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    if hasattr(value, "item"):
        value = value.item()
    return str(value)


def _encode_bark_markers(markers: list[dict[str, Any]]) -> Optional[str]:
    if not markers:
        return None
    return json.dumps(markers, separators=(",", ":"), sort_keys=True)


def _decode_bark_markers(value) -> list[dict[str, Any]]:
    text = _optional_text(value)
    if not text:
        return []
    try:
        decoded = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(decoded, list):
        return []
    return [marker for marker in decoded if isinstance(marker, dict)]
