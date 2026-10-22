"""Provider-independent detection, persistence and request monitoring."""
from dataclasses import asdict
from pathlib import Path
import threading
import time
import uuid

from counter.domain.actions import PredictionService
from counter.domain.predictions import count
from counter.domain.ports import DetectionError
from counter.monitoring.request_monitor import RequestMonitor


class DetectionService:
    def __init__(self, local_factory, repo, monitor):
        self.local_factory = local_factory
        self.repo = repo
        self.monitor = RequestMonitor(monitor)
        self._local = None
        # Bound expensive inference work; YOLO's shared predictor is not thread-safe.
        self._inference_lock = threading.Lock()

    def run(self, image, size, threshold, session_id, counter, provider, detector, image_name, endpoint):
        request_id, start = uuid.uuid4().hex, time.time()
        try:
            with self._inference_lock:
                if detector is None:
                    if self._local is None:
                        self._local = self.local_factory()
                    detector = self._local
                predictions, annotated = PredictionService(detector).get_valid_predictions(image, threshold, session_id)
                counts = count(predictions)
                if counter:
                    self.repo.update_values(session_id, counts)
                totals = self.repo.read_values(session_id)
                original = None
                if annotated:
                    original = Path(annotated).with_name(request_id + "_original.jpg")
                    image.seek(0)
                    original.write_bytes(image.read())
                current_counts = {item.object_class: item.count for item in counts}
                total_counts = {item.object_class: item.count for item in totals}
                self.monitor.log_success(request_id, session_id, endpoint, image_name, threshold, start,
                                         current_counts, annotated, counter, total_counts if counter else None,
                                         provider=provider)
            def url(path):
                return f"/api/results/{session_id}/{Path(path).name}" if path else None
            return {
                "request_id": request_id, "session_id": session_id, "provider": provider,
                "image_name": image_name, "width": size[0], "height": size[1],
                "predictions": [asdict(item) for item in predictions],
                "counts": current_counts, "total_counts": total_counts,
                "detection_count": len(predictions), "class_count": len(current_counts),
                "mean_confidence": sum(p.score for p in predictions) / len(predictions) if predictions else None,
                "latency_ms": round((time.time() - start) * 1000), "counter": counter,
                "image_url": url(original), "annotated_url": url(annotated),
            }
        except Exception as error:
            # Adapter errors explicitly promise safe messages; unexpected errors stay private.
            message = str(error) if isinstance(error, DetectionError) else "Detection failed. Check the local model and storage configuration."
            self.monitor.log_failure(request_id, session_id, endpoint, image_name, threshold, start,
                                     message, getattr(error, "status_code", 500), counter, provider=provider)
            raise
