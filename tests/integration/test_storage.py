from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
import subprocess
import sys

import pytest

from counter import settings
from counter.domain.models import ObjectCount
from counter.domain.ports import Monitor, MonitoringReader, ObjectCountRepo


def counts(repo, session, classes=None):
    return {value.object_class: value.count for value in repo.read_values(session, classes)}


def test_ports_and_incremental_counts(storage):
    repo, monitor, reader = storage
    assert isinstance(repo, ObjectCountRepo)
    assert isinstance(monitor, Monitor)
    assert isinstance(reader, MonitoringReader)
    assert repo.read_values("missing") == []
    repo.update_values("session-1", [ObjectCount("cat", 2), ObjectCount("dog", 1)])
    repo.update_values("session-1", [ObjectCount("cat", 3)])
    repo.update_values("session-2", [ObjectCount("cat", 9)])
    assert counts(repo, "session-1") == {"cat": 5, "dog": 1}
    assert counts(repo, "session-2") == {"cat": 9}
    assert counts(repo, "session-1", ["cat", "rabbit"]) == {"cat": 5}
    assert counts(repo, "session-1", []) == {}
    assert counts(repo, "session-1", ["missing"]) == {}
    repo.update_values("session-1", [])
    assert counts(settings.get_repo(), "session-1") == {"cat": 5, "dog": 1}
    assert sorted(reader.read_counters(), key=lambda row: (row["session_id"], row["object_class"])) == [
        {"session_id": "session-1", "object_class": "cat", "count": 5},
        {"session_id": "session-1", "object_class": "dog", "count": 1},
        {"session_id": "session-2", "object_class": "cat", "count": 9},
    ]


def test_parameterized_values_and_duplicate_classes(storage):
    repo, _, _ = storage
    session = "session'); DROP TABLE counter; --"
    name = "猫'); DELETE FROM counter; --"
    repo.update_values(session, [ObjectCount(name, 2), ObjectCount(name, 3)])
    assert counts(repo, session, [name]) == {name: 5}
    assert repo.read_values("other") == []


def test_concurrent_increments(storage):
    repo, _, _ = storage
    # Existing key verifies lost-update protection across concurrent connections.
    repo.update_values("concurrent", [ObjectCount("cat", 0)])
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: repo.update_values("concurrent", [ObjectCount("cat", 1)]), range(80)))
    assert counts(repo, "concurrent") == {"cat": 80}


@pytest.mark.parametrize("success,counter", [(True, True), (True, False), (False, True), (False, None)])
def test_request_history_round_trip(storage, success, counter):
    _, monitor, reader = storage
    before = datetime.now(timezone.utc)
    document = dict(
        request_id="request-1", session_id="session-1", endpoint="/object-detection",
        image_name="猫.jpg", threshold=0.75, response_time_ms=12,
        detected_count=2 if success else 0, detected_classes="cat" if success else "",
        counts={"cat": 2} if success else {}, status_code=200 if success else 500,
        success=success, error_message=None if success else "bad image",
        result_image_path="results/session-1/image.jpg" if success else None,
        counter=counter, persisted_counts={"cat": 8} if success and counter else None,
    )
    monitor.log_request(**document)
    rows = reader.read_requests()
    assert len(rows) == 1
    timestamp = rows[0].pop("request_timestamp")
    if timestamp.tzinfo is None:  # PyMongo's default UTC representation.
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    assert before.timestamp() - 0.001 <= timestamp.timestamp() <= datetime.now(timezone.utc).timestamp()
    assert rows[0] == document
    assert len(settings.get_monitoring_reader().read_requests()) == 1


def test_dashboard_loads_selected_database(storage):
    from monitoring import helpers
    repo, monitor, _ = storage
    repo.update_values("session-1", [ObjectCount("cat", 3)])
    for session in ("session-1", "perf-test-excluded"):
        monitor.log_request(
            "request-1", session, "/object-detection", "image.jpg", 0.5, 10,
            3, "cat", {"cat": 3}, 200, True, counter=True, persisted_counts={"cat": 3},
        )
    frame = helpers.load_requests_df()
    assert list(frame["session_id"]) == ["session-1"]
    assert frame.iloc[0]["counts"] == {"cat": 3}
    assert helpers.load_session_counters() == {"session-1": {"cat": 3}}


def test_explicit_reset_clears_counts_and_history(storage):
    repo, monitor, reader = storage
    repo.update_values("session-1", [ObjectCount("cat", 2)])
    monitor.log_request("request-1", "session-1", "/object-detection", "image.jpg",
        0.5, 10, 2, "cat", {"cat": 2}, 200, True)
    subprocess.run([sys.executable, "scripts/reset_database.py"], check=True, env={
        **os.environ, "DATABASE_BACKEND": settings.DATABASE_BACKEND,
        "MONGO_HOST": settings.MONGO_HOST, "MONGO_PORT": str(settings.MONGO_PORT),
        "MONGO_DB": settings.MONGO_DB, "SQLITE_PATH": settings.SQLITE_PATH,
    })
    assert reader.read_requests() == []
    assert repo.read_values("session-1") == []
    repo.update_values("session-1", [ObjectCount("cat", 1)])
    assert counts(repo, "session-1") == {"cat": 1}
