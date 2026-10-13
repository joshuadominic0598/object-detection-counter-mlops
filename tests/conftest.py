import uuid

import pytest

from counter import settings


@pytest.fixture(autouse=True)
def isolated_database(request, monkeypatch, tmp_path):
    """Never use the application's counts/history as test data."""
    if request.node.path.parent.name not in {"integration", "entrypoints", "e2e"}:
        yield
        return
    database = "counter_test_" + uuid.uuid4().hex
    monkeypatch.setattr(settings, "SQLITE_PATH", str(tmp_path / "counter.sqlite3"))
    monkeypatch.setattr(settings, "MONGO_DB", database)
    yield
    if settings.DATABASE_BACKEND == "mongodb":
        from pymongo import MongoClient
        with MongoClient(settings.MONGO_HOST, settings.MONGO_PORT) as client:
            client.drop_database(database)


@pytest.fixture
def storage():
    return settings.get_repo(), settings.get_monitor(), settings.get_monitoring_reader()
