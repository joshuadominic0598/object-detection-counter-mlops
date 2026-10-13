from typing import List

from counter.adapters.database.sqlite_store import SQLiteStore
from counter.domain.models import ObjectCount
from counter.domain.ports import ObjectCountRepo


class CountSQLiteRepo(ObjectCountRepo):
    def __init__(self, path):
        self.store = SQLiteStore(path)

    def read_values(self, session_id: str, object_classes: List[str] = None) -> List[ObjectCount]:
        query = "SELECT object_class, count FROM counter WHERE session_id = ?"
        parameters = [session_id]
        if object_classes is not None:
            if not object_classes:
                return []
            query += " AND object_class IN (" + ",".join("?" for _ in object_classes) + ")"
            parameters.extend(object_classes)
        with self.store.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [ObjectCount(row["object_class"], row["count"]) for row in rows]

    def update_values(self, session_id: str, new_values: List[ObjectCount]):
        with self.store.connect() as connection:
            connection.executemany(
                """INSERT INTO counter (session_id, object_class, count) VALUES (?, ?, ?)
                   ON CONFLICT (session_id, object_class)
                   DO UPDATE SET count = counter.count + excluded.count""",
                [(session_id, value.object_class, value.count) for value in new_values],
            )
