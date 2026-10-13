from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from counter.adapters.database.count_sqlite_repo import CountSQLiteRepo
from counter.domain.models import ObjectCount


def test_sqlite_persists_after_reopening(tmp_path):
    path = tmp_path / "nested" / "counter.sqlite3"
    CountSQLiteRepo(path).update_values("one", [ObjectCount("cat", 2)])
    assert CountSQLiteRepo(path).read_values("one") == [ObjectCount("cat", 2)]


def test_sqlite_concurrent_new_connections(tmp_path):
    path = tmp_path / "counter.sqlite3"
    CountSQLiteRepo(path)
    def increment(_):
        CountSQLiteRepo(path).update_values("one", [ObjectCount("cat", 1)])
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(increment, range(40)))
    assert CountSQLiteRepo(path).read_values("one") == [ObjectCount("cat", 40)]


def test_sqlite_batch_rolls_back_on_invalid_value(tmp_path):
    repo = CountSQLiteRepo(tmp_path / "counter.sqlite3")
    with pytest.raises(sqlite3.IntegrityError):
        repo.update_values("one", [ObjectCount("cat", 2), ObjectCount(None, 1)])
    assert repo.read_values("one") == []


def test_sqlite_rejects_ephemeral_connections():
    with pytest.raises(ValueError, match="persistent file"):
        CountSQLiteRepo(":memory:")
