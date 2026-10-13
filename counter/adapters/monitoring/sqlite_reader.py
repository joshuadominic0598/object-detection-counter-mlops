import json
from datetime import datetime

from counter.adapters.database.sqlite_store import SQLiteStore
from counter.domain.ports import MonitoringReader


class SQLiteMonitoringReader(MonitoringReader):
    def __init__(self, path):
        self.store = SQLiteStore(path)

    def read_requests(self):
        with self.store.connect() as connection:
            rows = connection.execute("SELECT document FROM detection_history ORDER BY id").fetchall()
        documents = [json.loads(row["document"]) for row in rows]
        for document in documents:
            document["request_timestamp"] = datetime.fromisoformat(document["request_timestamp"])
        return documents

    def read_counters(self):
        with self.store.connect() as connection:
            rows = connection.execute("SELECT session_id, object_class, count FROM counter").fetchall()
        return [dict(row) for row in rows]
