"""Roboflow hosted inference behind the same port as the local YOLO detector.

Use the SDK's documented HTTP wire format without adding its ML dependencies.
Only fixed Roboflow origins are reachable; users supply identifiers, never URLs.
"""
import base64
import math
import re
from dataclasses import dataclass, field

import httpx
from PIL import Image

from counter.domain.models import Box, Prediction
from counter.domain.ports import DetectionError, ObjectDetector


class RoboflowError(DetectionError):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class RoboflowOptions:
    api_key: str = field(repr=False)
    mode: str = "workflow"
    workspace: str = "model-version2"
    workflow_id: str = "parking-detection-v3-logic"
    model_id: str = ""
    output_path: str = "predictions"

    def __post_init__(self):
        if not self.api_key or len(self.api_key) > 256 or any(ord(c) < 33 or ord(c) > 126 for c in self.api_key):
            raise ValueError("Enter a valid Roboflow API key.")
        if self.mode not in {"workflow", "model"}:
            raise ValueError("Roboflow mode must be workflow or model.")
        slug = r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}"
        if self.mode == "workflow":
            if not re.fullmatch(slug, self.workspace) or not re.fullmatch(slug, self.workflow_id):
                raise ValueError("Use workspace and workflow slugs, not URLs or document IDs.")
        elif not re.fullmatch(slug + r"/[1-9][0-9]{0,6}", self.model_id):
            raise ValueError("Model ID must be project-slug/version (for example parking/3).")
        if not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){0,7}", self.output_path) or len(self.output_path) > 200:
            raise ValueError("Prediction output must be a dot-separated field path.")


class RoboflowDetector(ObjectDetector):
    MAX_RESPONSE_BYTES = 20 * 1024 * 1024

    def __init__(self, options: RoboflowOptions):
        self.options = options

    def predict(self, image):
        image.seek(0)
        with Image.open(image) as opened:
            width, height = opened.size
        image.seek(0)
        encoded = base64.b64encode(image.read()).decode("ascii")
        if self.options.mode == "workflow":
            url = f"https://serverless.roboflow.com/{self.options.workspace}/workflows/{self.options.workflow_id}"
            payload = {"inputs": {"image": {"type": "base64", "value": encoded}}, "use_cache": True}
            kwargs = {"json": payload}
        else:
            url = f"https://detect.roboflow.com/{self.options.model_id}"
            # The user's threshold is applied consistently after provider inference.
            kwargs = {"content": encoded, "params": {"confidence": 0},
                      "headers": {"Content-Type": "application/x-www-form-urlencoded"}}
        try:
            with httpx.Client(timeout=httpx.Timeout(90, connect=10), follow_redirects=False, trust_env=False) as client:
                with client.stream("POST", url,
                                   headers={"Authorization": f"Bearer {self.options.api_key}", **kwargs.pop("headers", {})},
                                   **kwargs) as response:
                    if response.status_code != 200:
                        messages = {
                            401: "Roboflow rejected the API key. Check your key and workspace access.",
                            403: "Roboflow denied access. Check your key and deployment permissions.",
                            404: "Roboflow deployment not found. Check the slugs or model version.",
                            429: "Roboflow rate limit reached. Wait before trying again.",
                        }
                        raise RoboflowError(messages.get(response.status_code, "Roboflow could not run this deployment."),
                                            429 if response.status_code == 429 else 502)
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > self.MAX_RESPONSE_BYTES:
                            raise RoboflowError("Roboflow response is too large. Expose a predictions-only workflow output.")
                    import json
                    data = json.loads(raw)
        except httpx.TimeoutException:
            raise RoboflowError("Roboflow timed out. Please try again.", 504) from None
        except (httpx.HTTPError, ValueError):
            # Never propagate upstream bodies, URLs, or exceptions that may contain secrets.
            raise RoboflowError("Could not read a valid response from Roboflow.") from None
        return self._parse(data, width, height)

    def _parse(self, data, width, height):
        if self.options.mode == "workflow":
            outputs = data.get("outputs") if isinstance(data, dict) else None
            if not isinstance(outputs, list) or len(outputs) != 1 or not isinstance(outputs[0], dict):
                raise RoboflowError("Expected one workflow result for one image.")
            selected = outputs[0]
            for part in self.options.output_path.split("."):
                if not isinstance(selected, dict) or part not in selected:
                    raise RoboflowError("Workflow must expose detection predictions. Set Prediction output to its output field name.")
                selected = selected[part]
        else:
            selected = data
        source_width, source_height = width, height
        if isinstance(selected, dict):
            source_image = selected.get("image", {})
            if isinstance(source_image, dict):
                source_width = source_image.get("width", width)
                source_height = source_image.get("height", height)
            selected = selected.get("predictions")
        if not isinstance(selected, list) or len(selected) > 10000:
            raise RoboflowError("Deployment must return object-detection predictions with bounding boxes.")
        try:
            sx, sy = width / float(source_width), height / float(source_height)
            if not math.isfinite(sx) or not math.isfinite(sy) or min(sx, sy) <= 0:
                raise ValueError()
            predictions = []
            for item in selected:
                label = item["class"]
                x, y, w, h, score = [float(item[k]) for k in ("x", "y", "width", "height", "confidence")]
                if (not isinstance(label, str) or not label or len(label) > 200 or
                        not all(math.isfinite(v) for v in (x, y, w, h, score)) or
                        w <= 0 or h <= 0 or not 0 <= score <= 1):
                    raise ValueError()
                box = Box(max(0, (x-w/2)*sx), max(0, (y-h/2)*sy),
                          min(width, (x+w/2)*sx), min(height, (y+h/2)*sy))
                if box.xmax > box.xmin and box.ymax > box.ymin:
                    predictions.append(Prediction(label, score, box))
            return predictions
        except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
            raise RoboflowError("Unsupported detection output. Expose boxes with class, confidence, x, y, width and height.") from None
