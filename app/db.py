"""The SQLite store: one connection per thread, the schema, numbered migrations,
and the settings table with an in-memory cache."""
from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from . import config

log = logging.getLogger("yue2.db")

_local = threading.local()


def conn() -> sqlite3.Connection:
    """A connection for this thread, opened once.  Route handlers run on the event
    loop thread or in the threadpool, so each gets its own and none is shared."""
    path = str(config.DB_PATH)
    current = getattr(_local, "conn", None)
    if current is None or getattr(_local, "path", None) != path:
        current = sqlite3.connect(path, timeout=15)
        current.row_factory = sqlite3.Row
        _local.conn = current
        _local.path = path
    return current


def rows(sql: str, args: tuple | dict = ()) -> list[dict]:
    return [dict(r) for r in conn().execute(sql, args).fetchall()]


def one(sql: str, args: tuple | dict = ()) -> dict | None:
    got = rows(sql, args)
    return got[0] if got else None


def execute(sql: str, args: tuple | dict = ()) -> int:
    c = conn()
    with c:
        return c.execute(sql, args).rowcount


# ---------------------------------------------------------------------- schema
BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    engine_file TEXT,
    sha256 TEXT NOT NULL,
    created_at REAL NOT NULL,
    abc TEXT,
    abc_updated_at REAL,
    transcribe_state TEXT NOT NULL DEFAULT 'none',
    transcribe_error TEXT
);
CREATE TABLE IF NOT EXISTS takes (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'cover',
    source_id TEXT,
    title TEXT NOT NULL,
    style TEXT NOT NULL,
    lyrics TEXT NOT NULL,
    abc TEXT,
    mode TEXT NOT NULL,
    seed INTEGER NOT NULL,
    checkpoint TEXT NOT NULL,
    max_duration REAL NOT NULL DEFAULT 360,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT,
    prompt_id TEXT,
    audio_path TEXT,
    duration REAL,
    error TEXT,
    favourite INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    finished_at REAL,
    elapsed REAL,
    auto_render INTEGER NOT NULL DEFAULT 0,
    variety TEXT NOT NULL DEFAULT 'normal',
    harmony INTEGER NOT NULL DEFAULT 0,
    space_id TEXT NOT NULL DEFAULT 'default',
    interpretation TEXT NOT NULL DEFAULT 'standard'
);
CREATE TABLE IF NOT EXISTS spaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stem_sets (
    id TEXT PRIMARY KEY,
    take_id TEXT,
    source_id TEXT,
    title TEXT NOT NULL,
    model TEXT NOT NULL,
    wanted TEXT NOT NULL,
    fmt TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT,
    progress REAL NOT NULL DEFAULT 0,
    error TEXT,
    folder TEXT,
    created_at REAL NOT NULL,
    finished_at REAL,
    elapsed REAL
);
"""


def _columns(table: str) -> set[str]:
    return {row["name"] for row in rows(f"PRAGMA table_info({table})")}


def _legacy_takes() -> None:
    """Databases from before numbered migrations.  Older takes tables had a
    mandatory source_id and no kind; songs have no source."""
    cols = _columns("takes")
    if "kind" not in cols:
        log.info("migrating takes: adding kind and auto_render, allowing a null source")
        c = conn()
        c.executescript(
            """
            ALTER TABLE takes RENAME TO takes_old;
            """
            + BASE_SCHEMA
            + """
            INSERT INTO takes (id, kind, source_id, title, style, lyrics, abc, mode, seed, checkpoint,
                               max_duration, status, stage, prompt_id, audio_path, duration, error,
                               favourite, created_at, finished_at, elapsed, auto_render)
                SELECT id, 'cover', source_id, title, style, lyrics, abc, mode, seed, checkpoint,
                       max_duration, status, stage, prompt_id, audio_path, duration, error,
                       favourite, created_at, finished_at, elapsed, 0
                FROM takes_old;
            DROP TABLE takes_old;
            """
        )
        cols = _columns("takes")
    if "variety" not in cols:
        log.info("migrating takes: adding variety")
        execute("ALTER TABLE takes ADD COLUMN variety TEXT NOT NULL DEFAULT 'normal'")


def _harmony() -> None:
    if "harmony" not in _columns("takes"):
        execute("ALTER TABLE takes ADD COLUMN harmony INTEGER NOT NULL DEFAULT 0")


DEFAULT_SPACE = "default"


def _spaces() -> None:
    """Spaces hold takes.  Every take starts in Default, which cannot be deleted."""
    conn().executescript(BASE_SCHEMA)
    if "space_id" not in _columns("takes"):
        execute("ALTER TABLE takes ADD COLUMN space_id TEXT NOT NULL DEFAULT 'default'")
    execute("INSERT OR IGNORE INTO spaces(id, name, created_at) VALUES(?, 'Default', 0)", (DEFAULT_SPACE,))
    execute("CREATE INDEX IF NOT EXISTS takes_space ON takes(space_id, created_at)")


def _interpretation() -> None:
    if "interpretation" not in _columns("takes"):
        execute("ALTER TABLE takes ADD COLUMN interpretation TEXT NOT NULL DEFAULT 'standard'")


def _indexes() -> None:
    conn().executescript(
        """
        CREATE INDEX IF NOT EXISTS takes_created ON takes(created_at);
        CREATE INDEX IF NOT EXISTS takes_source ON takes(source_id);
        CREATE INDEX IF NOT EXISTS stem_sets_take ON stem_sets(take_id);
        CREATE INDEX IF NOT EXISTS stem_sets_source ON stem_sets(source_id);
        """
    )


# Each entry brings the database from its position in the list to the next version.
# Append only.  A migration must be safe on a database that is already partly there.
MIGRATIONS = [
    lambda: (conn().executescript(BASE_SCHEMA), _legacy_takes()),   # -> 1
    _indexes,                                                        # -> 2
    _harmony,                                                        # -> 3
    _spaces,                                                         # -> 4
    _interpretation,                                                 # -> 5
]


def migrate() -> None:
    """Create or bring the database up to date.  Safe to run on every start."""
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = conn()
    c.execute("PRAGMA journal_mode=WAL")
    version = c.execute("PRAGMA user_version").fetchone()[0]
    for number in range(version, len(MIGRATIONS)):
        log.info("database migration %d", number + 1)
        MIGRATIONS[number]()
        c.execute(f"PRAGMA user_version = {number + 1}")
        c.commit()
    _settings_cache.clear()


# -------------------------------------------------------------------- settings
_settings_cache: dict[str, str | None] = {}


def get_setting(key: str, default: str | None = None) -> str | None:
    if key not in _settings_cache:
        row = one("SELECT value FROM settings WHERE key = ?", (key,))
        _settings_cache[key] = row["value"] if row else None
    value = _settings_cache[key]
    return default if value is None else value


def set_setting(key: str, value: str) -> None:
    execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    _settings_cache[key] = value


def bump_average(kind: str, seconds: float) -> None:
    key = f"avg_{kind}_seconds"
    old = get_setting(key)
    new = seconds if not old else (float(old) * 0.6 + seconds * 0.4)
    set_setting(key, f"{new:.1f}")
