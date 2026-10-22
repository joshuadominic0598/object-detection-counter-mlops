from pathlib import Path

from fastapi.testclient import TestClient

from counter import config, settings
from counter.domain.models import Box, ObjectCount, Prediction
from counter.domain.ports import ObjectDetector
from counter.entrypoints.webapp import create_app


class OneCatDetector(ObjectDetector):
    def predict(self, image):
        return [Prediction("cat", 0.99, Box(0, 0, 10, 10))]


def test_api_counts_accumulate_and_list_mode_only_logs(monkeypatch):
    monkeypatch.setattr(config, "get_detector", OneCatDetector)
    image = (Path(__file__).resolve().parents[2] / "resources/images/carlot.jpeg").read_bytes()
    with TestClient(create_app()) as client:
        assert client.get("/health").json() == {"status": "ok"}
        for total in (1, 2):
            response = client.post("/object-detection",
                data={"session_id": "api-session", "counter": "true"},
                files={"file": ("image.jpg", image, "image/jpeg")})
            assert response.status_code == 200
            assert response.json() == {
                "current_objects": [{"object_class": "cat", "count": 1}],
                "total_objects": [{"object_class": "cat", "count": total}],
            }
        response = client.post("/object-detection", data={"session_id": "api-session"},
            files={"file": ("image.jpg", image, "image/jpeg")})
        assert response.status_code == 200
        assert len(response.json()) == 1
    assert settings.get_repo().read_values("api-session") == [ObjectCount("cat", 2)]
    rows = settings.get_monitoring_reader().read_requests()
    assert len(rows) == 3
    assert [row["counter"] for row in rows] == [True, True, False]
    assert [row["persisted_counts"] for row in rows] == [{"cat": 1}, {"cat": 2}, None]
    assert all(row["result_image_path"] for row in rows)


def test_prediction_failure_is_logged_in_selected_database(monkeypatch):
    class BrokenDetector(ObjectDetector):
        def predict(self, image):
            raise ValueError("prediction failed")
    monkeypatch.setattr(config, "get_detector", BrokenDetector)
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        response = client.post("/object-detection",
            data={"session_id": "failed-session", "counter": "true"},
            files={"file": ("image.jpg", (Path(__file__).resolve().parents[2] / "resources/images/carlot.jpeg").read_bytes(), "image/jpeg")})
    assert response.status_code == 500
    assert settings.get_repo().read_values("failed-session") == []
    rows = settings.get_monitoring_reader().read_requests()
    assert len(rows) == 1
    assert rows[0]["success"] is False
    assert rows[0]["error_message"] == "Detection failed. Check the local model and storage configuration."
    assert rows[0]["counter"] is True
    assert rows[0]["counts"] == {}
    assert rows[0]["persisted_counts"] is None
