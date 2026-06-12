"""Configuration loading and validation."""

from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
import bcrypt

logger = logging.getLogger(__name__)

LEGACY_MIGRATION_KEY = "legacy_config_migrated"
AUTH_USERNAME_KEY = "auth.username"
AUTH_PASSWORD_HASH_KEY = "auth.password_hash"
AUTH_SESSION_SECRET_KEY = "auth.session_secret"
AUTH_CREATED_KEY = "auth.created"
AUTH_RESET_SENTINEL = "reset-dashboard-login"


@dataclass
class LocationConfig:
    address: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None


@dataclass
class AudioConfig:
    device: Optional[int | str] = None
    sample_rate: int = 16000
    channels: int = 2


@dataclass
class DetectionConfig:
    threshold: float = 0.15
    window_sec: float = 0.5


@dataclass
class IncidentsConfig:
    min_barks: int = 2
    gap_sec: float = 15.0  # 15 sec silence = incident ends
    min_duration_sec: float = 1.0
    merge_within_sec: float = 10.0
    pre_roll_sec: float = 15.0


@dataclass
class DeterrenceConfig:
    enabled: bool = True
    audible_enabled: bool = False
    ultrasonic_enabled: bool = False
    manual_enabled: bool = True
    auto_enabled: bool = False
    assertiveness: str = "assertive"
    bark_score_threshold: float = 0.15
    cooldown_sec: float = 10.0
    burst_sec: float = 2.0
    max_fires_per_incident: int = 3
    max_fires_per_day: int = 50
    quiet_hours_enabled: bool = False
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "07:00"
    ultrasonic_gpio_pin: Optional[int] = None
    ultrasonic_active_high: bool = True
    audible_output_device: Optional[int | str] = None
    audible_profile: str = "chirp"


@dataclass
class StorageConfig:
    data_dir: Path = field(default_factory=lambda: Path("./data"))
    retention_days: int = 0

    def __post_init__(self):
        if isinstance(self.data_dir, str):
            self.data_dir = Path(self.data_dir)


@dataclass
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class Config:
    location: LocationConfig = field(default_factory=LocationConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    incidents: IncidentsConfig = field(default_factory=IncidentsConfig)
    deterrence: DeterrenceConfig = field(default_factory=DeterrenceConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    web: WebConfig = field(default_factory=WebConfig)


def load_config(path: Path) -> Config:
    """Load configuration from YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    return Config(
        location=LocationConfig(**data.get("location", {})),
        audio=AudioConfig(**data.get("audio", {})),
        detection=DetectionConfig(**data.get("detection", {})),
        incidents=IncidentsConfig(**data.get("incidents", {})),
        deterrence=DeterrenceConfig(**data.get("deterrence", {})),
        storage=StorageConfig(**data.get("storage", {})),
        web=WebConfig(**data.get("web", {})),
    )


def get_data_dir() -> Path:
    """Return the runtime data directory.

    The data directory is intentionally bootstrapped outside live settings so
    the app always knows which SQLite database to open before settings exist.
    """
    return Path(os.environ.get("DOG_DETECTOR_DATA_DIR", "./data"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _config_to_sections(config: Config) -> dict[str, dict[str, Any]]:
    return {
        "location": asdict(config.location),
        "audio": asdict(config.audio),
        "detection": asdict(config.detection),
        "incidents": asdict(config.incidents),
        "deterrence": asdict(config.deterrence),
        "storage": {"retention_days": config.storage.retention_days},
        "web": asdict(config.web),
    }


def _config_from_sections(sections: dict[str, dict[str, Any]], data_dir: Path) -> Config:
    defaults = _config_to_sections(Config(storage=StorageConfig(data_dir=data_dir)))

    merged = {}
    for section, values in defaults.items():
        section_values = values.copy()
        section_values.update(sections.get(section, {}) or {})
        merged[section] = section_values

    return Config(
        location=LocationConfig(**merged["location"]),
        audio=AudioConfig(**merged["audio"]),
        detection=DetectionConfig(**merged["detection"]),
        incidents=IncidentsConfig(**merged["incidents"]),
        deterrence=DeterrenceConfig(**merged["deterrence"]),
        storage=StorageConfig(
            data_dir=data_dir,
            retention_days=int(merged["storage"].get("retention_days", 0) or 0),
        ),
        web=WebConfig(**merged["web"]),
    )


class SettingsStore:
    """SQLite-backed runtime settings store."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "events.sqlite"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key        TEXT PRIMARY KEY,
                    value      TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def get(self, key: str, default: Any = None) -> Any:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()

        if row is None:
            return default

        try:
            return json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return default

    def set(self, key: str, value: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(value), _utc_now()),
            )
            conn.commit()

    def has(self, key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM settings WHERE key = ?", (key,)).fetchone()
        return row is not None

    def get_section(self, section: str) -> dict[str, Any]:
        value = self.get(section, {})
        return value if isinstance(value, dict) else {}

    def set_section(self, section: str, value: dict[str, Any]) -> None:
        self.set(section, value)

    def seed_defaults(self, config: Config) -> None:
        for section, values in _config_to_sections(config).items():
            if not self.has(section):
                self.set_section(section, values)

    def load_config(self, data_dir: Path) -> Config:
        sections = {
            section: self.get_section(section)
            for section in (
                "location",
                "audio",
                "detection",
                "incidents",
                "deterrence",
                "storage",
                "web",
            )
        }
        return _config_from_sections(sections, data_dir)

    def update_config(self, config: Config) -> None:
        for section, values in _config_to_sections(config).items():
            self.set_section(section, values)

    def ensure_auth_credentials(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        reset: bool = False,
    ) -> Optional[dict[str, str]]:
        """Create dashboard username/password once and return plaintext only if new."""
        if not reset and self.has(AUTH_USERNAME_KEY) and self.has(AUTH_PASSWORD_HASH_KEY):
            self.ensure_session_secret()
            return None

        created_username = (
            username
            or os.environ.get("DOG_DETECTOR_AUTH_USERNAME")
            or (self.get_auth_username() if reset else None)
            or "admin"
        )
        created_password = password or os.environ.get("DOG_DETECTOR_AUTH_PASSWORD") or secrets.token_urlsafe(18)
        self.set(AUTH_USERNAME_KEY, created_username)
        self.set(AUTH_PASSWORD_HASH_KEY, hash_password(created_password))
        self.set(
            AUTH_CREATED_KEY,
            {
                "created_at": _utc_now(),
                "source": _auth_source(password=password, reset=reset),
            },
        )
        if reset:
            self.set(AUTH_SESSION_SECRET_KEY, secrets.token_urlsafe(32))
        else:
            self.ensure_session_secret()
        return {"username": created_username, "password": created_password}

    def ensure_session_secret(self) -> str:
        value = self.get(AUTH_SESSION_SECRET_KEY)
        if isinstance(value, str) and value:
            return value

        secret = secrets.token_urlsafe(32)
        self.set(AUTH_SESSION_SECRET_KEY, secret)
        return secret

    def get_auth_username(self) -> Optional[str]:
        value = self.get(AUTH_USERNAME_KEY)
        return value if isinstance(value, str) else None

    def get_auth_password_hash(self) -> Optional[str]:
        value = self.get(AUTH_PASSWORD_HASH_KEY)
        return value if isinstance(value, str) else None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _auth_source(password: Optional[str], reset: bool) -> str:
    if reset and (password or os.environ.get("DOG_DETECTOR_AUTH_PASSWORD")):
        return "reset-env"
    if reset:
        return "reset-generated"
    if password or os.environ.get("DOG_DETECTOR_AUTH_PASSWORD"):
        return "env"
    return "generated"


def _auth_reset_sentinel(data_dir: Path) -> Path:
    return data_dir / AUTH_RESET_SENTINEL


def _auth_reset_requested(data_dir: Path) -> bool:
    return _env_truthy("DOG_DETECTOR_RESET_AUTH") or _auth_reset_sentinel(data_dir).exists()


def _clear_auth_reset_sentinel(data_dir: Path) -> None:
    sentinel = _auth_reset_sentinel(data_dir)
    if not sentinel.exists():
        return
    try:
        sentinel.unlink()
    except OSError as exc:
        logger.warning("Could not remove auth reset marker %s: %s", sentinel, exc)


def load_runtime_config(
    data_dir: Optional[Path] = None,
    legacy_config_path: Path = Path("config.yaml"),
) -> tuple[Config, SettingsStore, Optional[dict[str, str]]]:
    """Load runtime config from SQLite, migrating config.yaml once if present.

    Returns:
        Config, SettingsStore, generated dashboard credentials if this startup
        created them.
    """
    resolved_data_dir = Path(data_dir) if data_dir is not None else get_data_dir()
    store = SettingsStore(resolved_data_dir)
    default_config = Config(storage=StorageConfig(data_dir=resolved_data_dir))

    if legacy_config_path.exists() and not store.has(LEGACY_MIGRATION_KEY):
        migrated_config = load_config(legacy_config_path)
        migrated_config.storage.data_dir = resolved_data_dir
        store.update_config(migrated_config)
        store.set(LEGACY_MIGRATION_KEY, True)
        _rename_legacy_config(legacy_config_path)
        logger.info("Migrated config.yaml into SQLite settings")
    else:
        store.seed_defaults(default_config)

    reset_auth = _auth_reset_requested(resolved_data_dir)
    generated_credentials = store.ensure_auth_credentials(reset=reset_auth)
    if reset_auth:
        _clear_auth_reset_sentinel(resolved_data_dir)

    if generated_credentials:
        if reset_auth:
            logger.warning(
                "Reset dashboard login credentials: username=%s password=%s",
                generated_credentials["username"],
                generated_credentials["password"],
            )
        else:
            logger.warning(
                "Generated dashboard login credentials: username=%s password=%s",
                generated_credentials["username"],
                generated_credentials["password"],
            )

    return store.load_config(resolved_data_dir), store, generated_credentials


def _rename_legacy_config(path: Path) -> None:
    migrated_path = path.with_name(f"{path.name}.migrated")
    try:
        if migrated_path.exists():
            logger.warning("Leaving %s in place because %s already exists", path, migrated_path)
            return
        path.rename(migrated_path)
    except OSError as exc:
        logger.warning("Could not rename migrated legacy config %s: %s", path, exc)
