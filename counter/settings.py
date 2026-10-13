"""Storage settings shared by the app and dashboard composition roots."""

import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_BACKEND = os.getenv("DATABASE_BACKEND", "mongodb").strip().lower()
if DATABASE_BACKEND not in {"mongodb", "sqlite"}:
    raise ValueError("DATABASE_BACKEND must be 'mongodb' or 'sqlite'")

MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))
MONGO_DB = os.getenv("MONGO_DB", "counter")
SQLITE_PATH = os.getenv("SQLITE_PATH", "tmp/sqlite/counter.sqlite3")


def get_repo():
    if DATABASE_BACKEND == "sqlite":
        from counter.adapters.database.count_sqlite_repo import CountSQLiteRepo
        return CountSQLiteRepo(SQLITE_PATH)
    from counter.adapters.database.count_mongo_repo import CountMongoDBRepo
    return CountMongoDBRepo(MONGO_HOST, MONGO_PORT, MONGO_DB)


def get_monitor():
    if DATABASE_BACKEND == "sqlite":
        from counter.adapters.monitoring.sqlite_monitor import SQLiteMonitor
        return SQLiteMonitor(SQLITE_PATH)
    from counter.adapters.monitoring.mongo_monitor import MongoMonitor
    return MongoMonitor(MONGO_HOST, MONGO_PORT, MONGO_DB)


def get_monitoring_reader():
    if DATABASE_BACKEND == "sqlite":
        from counter.adapters.monitoring.sqlite_reader import SQLiteMonitoringReader
        return SQLiteMonitoringReader(SQLITE_PATH)
    from counter.adapters.monitoring.mongo_reader import MongoMonitoringReader
    return MongoMonitoringReader(MONGO_HOST, MONGO_PORT, MONGO_DB)
