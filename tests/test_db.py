import sqlite3

from app import config, db


def test_fresh_database_is_at_the_latest_version():
    assert db.conn().execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    names = {r["name"] for r in db.rows("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"takes_created", "takes_source", "stem_sets_take", "stem_sets_source"} <= names


def test_legacy_takes_table_is_rebuilt(tmp_path, monkeypatch):
    path = tmp_path / "old.sqlite"
    legacy = sqlite3.connect(path)
    legacy.executescript(
        """CREATE TABLE takes (id TEXT PRIMARY KEY, source_id TEXT NOT NULL, title TEXT NOT NULL,
               style TEXT NOT NULL, lyrics TEXT NOT NULL, abc TEXT, mode TEXT NOT NULL, seed INTEGER NOT NULL,
               checkpoint TEXT NOT NULL, max_duration REAL NOT NULL DEFAULT 360, status TEXT NOT NULL DEFAULT 'queued',
               stage TEXT, prompt_id TEXT, audio_path TEXT, duration REAL, error TEXT,
               favourite INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, finished_at REAL, elapsed REAL);
           INSERT INTO takes (id, source_id, title, style, lyrics, mode, seed, checkpoint, created_at)
               VALUES ('t1', 's1', 'Old', 'rock', 'la', 'full', 7, 'ck', 1.0);"""
    )
    legacy.commit()
    legacy.close()
    monkeypatch.setattr(config, "DB_PATH", path)
    db.migrate()
    take = db.one("SELECT * FROM takes WHERE id = 't1'")
    assert take["kind"] == "cover" and take["variety"] == "normal" and take["seed"] == 7
    db.migrate()   # a second run changes nothing
    assert db.conn().execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)


def test_settings_cache_follows_writes():
    assert db.get_setting("x", "fallback") == "fallback"
    db.set_setting("x", "1")
    assert db.get_setting("x") == "1"
