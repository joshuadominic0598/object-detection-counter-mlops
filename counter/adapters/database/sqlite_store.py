"""Local SQLite connections: short transactions and no shared thread state."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path


class SQLiteStore:
    def __init__(self, path):
        if str(path) == ":memory:":
            raise ValueError("SQLite adapters require a persistent file path")
        self.path = str(Path(path).expanduser().resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS counter (
                    session_id TEXT NOT NULL,
                    object_class TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    PRIMARY KEY (session_id, object_class)
                );
                CREATE TABLE IF NOT EXISTS detection_history (
                    id INTEGER PRIMARY KEY,
                    document TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()
