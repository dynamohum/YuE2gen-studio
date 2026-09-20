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
    interpretation TEXT NOT NULL DEFAULT 'standard',
    feel TEXT NOT NULL DEFAULT 'steady',
    realaudio INTEGER NOT NULL DEFAULT 0,
    identity_id TEXT,
    persona_id TEXT,
    voice_lora TEXT,
    voice_lora_strength REAL NOT NULL DEFAULT 1.0
);
CREATE TABLE IF NOT EXISTS identities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    trigger_word TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    voice TEXT NOT NULL DEFAULT '',
    folder TEXT NOT NULL,
    consent INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    exported_at REAL,
    export_dir TEXT,
    lora TEXT
);
CREATE TABLE IF NOT EXISTS identity_songs (
    id TEXT PRIMARY KEY,
    identity_id TEXT NOT NULL,
    file TEXT NOT NULL,
    title TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    duration REAL,
    bit_rate INTEGER,
    include INTEGER NOT NULL DEFAULT 1,
    flag TEXT,
    stored_path TEXT,
    vocals_state TEXT NOT NULL DEFAULT 'none',
    score_state TEXT NOT NULL DEFAULT 'none',
    lyrics_state TEXT NOT NULL DEFAULT 'none',
    style_state TEXT NOT NULL DEFAULT 'none',
    error TEXT,
    key TEXT,
    tempo INTEGER,
    lyrics TEXT NOT NULL DEFAULT '',
    lyrics_checked INTEGER NOT NULL DEFAULT 0,
    style_hint TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT ''
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


def _feel() -> None:
    if "feel" not in _columns("takes"):
        execute("ALTER TABLE takes ADD COLUMN feel TEXT NOT NULL DEFAULT 'steady'")


def _realaudio() -> None:
    if "realaudio" not in _columns("takes"):
        execute("ALTER TABLE takes ADD COLUMN realaudio INTEGER NOT NULL DEFAULT 0")


def _personas() -> None:
    conn().executescript(BASE_SCHEMA)
    tbls = {row["name"] for row in rows("SELECT name FROM sqlite_master WHERE type='table'")}
    if "persona_songs" in tbls:
        execute("CREATE INDEX IF NOT EXISTS persona_songs_persona ON persona_songs(persona_id, position)")
    if "identity_songs" in tbls:
        execute("CREATE INDEX IF NOT EXISTS identity_songs_identity ON identity_songs(identity_id, position)")


def _persona_song_description() -> None:
    tbls = {row["name"] for row in rows("SELECT name FROM sqlite_master WHERE type='table'")}
    for tbl in ("identity_songs", "persona_songs"):
        if tbl in tbls and "description" not in _columns(tbl):
            execute(f"ALTER TABLE {tbl} ADD COLUMN description TEXT NOT NULL DEFAULT ''")


def _persona_loras() -> None:
    tbls = {row["name"] for row in rows("SELECT name FROM sqlite_master WHERE type='table'")}
    for tbl in ("identities", "personas"):
        if tbl in tbls and "lora" not in _columns(tbl):
            execute(f"ALTER TABLE {tbl} ADD COLUMN lora TEXT")
    if "persona_id" not in _columns("takes"):
        execute("ALTER TABLE takes ADD COLUMN persona_id TEXT")
    if "identity_id" not in _columns("takes"):
        execute("ALTER TABLE takes ADD COLUMN identity_id TEXT")
    if "voice_lora" not in _columns("takes"):
        execute("ALTER TABLE takes ADD COLUMN voice_lora TEXT")
    if "voice_lora_strength" not in _columns("takes"):
        execute("ALTER TABLE takes ADD COLUMN voice_lora_strength REAL NOT NULL DEFAULT 1.0")


def _identities() -> None:
    tbls = {row["name"] for row in rows("SELECT name FROM sqlite_master WHERE type='table'")}
    if "personas" in tbls and "identities" not in tbls:
        execute("ALTER TABLE personas RENAME TO identities")
    elif "identities" not in tbls:
        conn().executescript(BASE_SCHEMA)

    if "persona_songs" in tbls and "identity_songs" not in tbls:
        execute("ALTER TABLE persona_songs RENAME TO identity_songs")
    elif "identity_songs" not in tbls:
        conn().executescript(BASE_SCHEMA)

    id_cols = _columns("identity_songs")
    if "persona_id" in id_cols and "identity_id" not in id_cols:
        execute("ALTER TABLE identity_songs RENAME COLUMN persona_id TO identity_id")

    take_cols = _columns("takes")
    if "identity_id" not in take_cols:
        execute("ALTER TABLE takes ADD COLUMN identity_id TEXT")
        if "persona_id" in take_cols:
            execute("UPDATE takes SET identity_id = persona_id WHERE identity_id IS NULL AND persona_id IS NOT NULL")
    if "persona_id" not in take_cols:
        execute("ALTER TABLE takes ADD COLUMN persona_id TEXT")

    execute("CREATE INDEX IF NOT EXISTS identity_songs_identity ON identity_songs(identity_id, position)")

    views = {row["name"] for row in rows("SELECT name FROM sqlite_master WHERE type='view'")}
    tbls_now = {row["name"] for row in rows("SELECT name FROM sqlite_master WHERE type='table'")}
    if "personas" not in tbls_now and "personas" not in views:
        conn().execute("CREATE VIEW personas AS SELECT * FROM identities")
    if "persona_songs" not in tbls_now and "persona_songs" not in views:
        conn().execute("CREATE VIEW persona_songs AS SELECT id, identity_id AS persona_id, identity_id, file, title, sha256, duration, bit_rate, include, flag, stored_path, vocals_state, score_state, lyrics_state, style_state, error, key, tempo, lyrics, lyrics_checked, style_hint, position, description FROM identity_songs")


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
def _vocal_check() -> None:
    """An instrumental keeps what a check of its finished audio found: the share
    of it that carries singing, or NULL while nothing has looked."""
    if "vocal_check" not in _columns("takes"):
        execute("ALTER TABLE takes ADD COLUMN vocal_check REAL")


def _style_lora() -> None:
    """A take keeps the style LoRA it was rendered through and both of its
    strengths, so the card can name it and Again can reproduce it."""
    columns = _columns("takes")
    if "style_lora" not in columns:
        execute("ALTER TABLE takes ADD COLUMN style_lora TEXT")
    if "style_lora_model" not in columns:
        execute("ALTER TABLE takes ADD COLUMN style_lora_model REAL NOT NULL DEFAULT 1.0")
    if "style_lora_clip" not in columns:
        execute("ALTER TABLE takes ADD COLUMN style_lora_clip REAL NOT NULL DEFAULT 1.0")


MIGRATIONS = [
    lambda: (conn().executescript(BASE_SCHEMA), _legacy_takes()),   # -> 1
    _indexes,                                                        # -> 2
    _harmony,                                                        # -> 3
    _spaces,                                                         # -> 4
    _interpretation,                                                 # -> 5
    _feel,                                                           # -> 6
    _realaudio,                                                      # -> 7
    _personas,                                                       # -> 8
    _persona_song_description,                                       # -> 9
    _persona_loras,                                                  # -> 10
    _identities,                                                     # -> 11
    _vocal_check,                                                    # -> 12
    _style_lora,                                                     # -> 13
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
