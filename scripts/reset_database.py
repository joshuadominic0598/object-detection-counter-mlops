"""Invoked only for an explicit database-reset flag during make start."""

from counter import settings

def main():
    if settings.DATABASE_BACKEND == "sqlite":
        from counter.adapters.database.sqlite_store import SQLiteStore
        with SQLiteStore(settings.SQLITE_PATH).connect() as connection:
            connection.execute("DELETE FROM counter")
            connection.execute("DELETE FROM detection_history")
    else:
        from pymongo import MongoClient
        with MongoClient(settings.MONGO_HOST, settings.MONGO_PORT) as client:
            client.drop_database(settings.MONGO_DB)

    print(f"Cleared application data in {settings.DATABASE_BACKEND}")


if __name__ == "__main__":
    main()
