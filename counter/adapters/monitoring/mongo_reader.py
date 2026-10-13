from pymongo import MongoClient

from counter.domain.ports import MonitoringReader


class MongoMonitoringReader(MonitoringReader):
    def __init__(self, host, port, database):
        self.host, self.port, self.database = host, port, database

    def read_requests(self):
        with MongoClient(self.host, self.port) as client:
            return list(client[self.database].detection_history.find({}, {"_id": 0}))

    def read_counters(self):
        with MongoClient(self.host, self.port) as client:
            return list(client[self.database].counter.find(
                {}, {"_id": 0, "session_id": 1, "object_class": 1, "count": 1},
            ))
