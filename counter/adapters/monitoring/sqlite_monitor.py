import json
from datetime import datetime, timezone

from counter.adapters.database.sqlite_store import SQLiteStore
from counter.domain.ports import Monitor


class SQLiteMonitor(Monitor):
    def __init__(self, path):
        self.store = SQLiteStore(path)

    def log_request(
        self, request_id: str, session_id: str, endpoint: str, image_name: str,
        threshold: float, response_time_ms: int, detected_count: int,
        detected_classes: str, counts: dict, status_code: int, success: bool,
        error_message: str = None, result_image_path: str = None,
        counter: bool = None, persisted_counts: dict = None,
    ):
        document = {
            "request_id": request_id,
            "session_id": session_id,
            "request_timestamp": datetime.now(timezone.utc).isoformat(),
            "endpoint": endpoint,
            "image_name": image_name,
            "threshold": threshold,
            "response_time_ms": response_time_ms,
            "detected_count": detected_count,
            "detected_classes": detected_classes,
            "counts": counts,
            "status_code": status_code,
            "success": success,
            "error_message": error_message,
            "result_image_path": result_image_path,
            "counter": counter,
            "persisted_counts": persisted_counts,
        }
        with self.store.connect() as connection:
            connection.execute(
                "INSERT INTO detection_history (document) VALUES (?)",
                (json.dumps(document),),
            )
