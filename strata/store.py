"""Snapshots over time, in one SQLite file.

The whole value of this tool is the history, so the history is the thing that
has to survive. One file, in your home directory, holding a few hundred rows
per scan — a year of nightly scans is a handful of megabytes, which is a
rounding error against the problem it describes.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

from .model import Snapshot

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id        INTEGER PRIMARY KEY,
    taken     REAL NOT NULL,
    root      TEXT NOT NULL,
    total     INTEGER NOT NULL DEFAULT 0,
    files     INTEGER NOT NULL DEFAULT 0,
    free      INTEGER NOT NULL DEFAULT 0,
    capacity  INTEGER NOT NULL DEFAULT 0,
    snapshot_bytes INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS scans_taken ON scans(taken);

CREATE TABLE IF NOT EXISTS sizes (
    scan  INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    path  TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    PRIMARY KEY (scan, path)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def default_path() -> Path:
    return Path.home() / ".strata" / "history.db"


class Store:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_path()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10.0)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(_SCHEMA)
        self.db.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.db.commit()

    # ------------------------------------------------------------- writing

    def save(self, snapshot: Snapshot) -> int:
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO scans (taken, root, total, files, free, capacity, snapshot_bytes)"
                " VALUES (?,?,?,?,?,?,?)",
                (snapshot.taken, snapshot.root, snapshot.total, snapshot.files,
                 snapshot.free, snapshot.capacity, snapshot.snapshot_bytes),
            )
            scan_id = int(cursor.lastrowid)
            self.db.executemany(
                "INSERT INTO sizes (scan, path, bytes) VALUES (?,?,?)",
                [(scan_id, path, size) for path, size in snapshot.entries.items()],
            )
        snapshot.id = scan_id
        return scan_id

    # ------------------------------------------------------------- reading

    def _hydrate(self, row: sqlite3.Row) -> Snapshot:
        entries = {
            r["path"]: r["bytes"]
            for r in self.db.execute("SELECT path, bytes FROM sizes WHERE scan = ?", (row["id"],))
        }
        return Snapshot(
            taken=row["taken"], root=row["root"], entries=entries, files=row["files"],
            total=row["total"], free=row["free"], capacity=row["capacity"],
            snapshot_bytes=row["snapshot_bytes"], id=row["id"],
        )

    def latest(self, *, offset: int = 0) -> Snapshot | None:
        row = self.db.execute(
            "SELECT * FROM scans ORDER BY taken DESC LIMIT 1 OFFSET ?", (offset,)
        ).fetchone()
        return self._hydrate(row) if row else None

    def nearest(self, when: float) -> Snapshot | None:
        """The scan closest to a moment, before or after.

        "Since Tuesday" means the scan nearest Tuesday, not the first one
        after it — otherwise asking about a day you did not scan silently
        answers about a different week.
        """
        row = self.db.execute(
            "SELECT * FROM scans ORDER BY ABS(taken - ?) LIMIT 1", (when,)
        ).fetchone()
        return self._hydrate(row) if row else None

    def all(self) -> list[Snapshot]:
        return [
            self._hydrate(row)
            for row in self.db.execute("SELECT * FROM scans ORDER BY taken")
        ]

    def summaries(self) -> Iterator[sqlite3.Row]:
        yield from self.db.execute("SELECT * FROM scans ORDER BY taken")

    def count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM scans").fetchone()[0])

    def prune(self, keep_days: int = 400) -> int:
        cutoff = (datetime.now() - timedelta(days=keep_days)).timestamp()
        with self.db:
            cursor = self.db.execute("DELETE FROM scans WHERE taken < ?", (cutoff,))
        return cursor.rowcount

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *_) -> None:
        self.close()
