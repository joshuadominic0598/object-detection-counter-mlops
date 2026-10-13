import os

from dotenv import load_dotenv

from counter.settings import get_repo, get_monitor
from counter.domain.actions import CountDetectedObjects, ListDetectedObjects

load_dotenv()

# Active model resolution
try:
    from model_management.model_registry.registry import resolve_model_path
    _ACTIVE_MODEL_PATH = str(resolve_model_path())
except Exception:
    # Registry missing/unreadable - fall back to the historical default
    _ACTIVE_MODEL_PATH = "tmp/models/yolo26.pt"

MODEL_PATH = os.getenv("MODEL_PATH") or _ACTIVE_MODEL_PATH

# Dependency wiring

def get_detector():
    from counter.adapters.detection.yolo_detector import YOLODetector
    return YOLODetector(MODEL_PATH)


def prod_count_action():
    return CountDetectedObjects(get_detector(), get_repo())


def prod_object_list_action():
    return ListDetectedObjects(get_detector())


def get_count_action():
    return prod_count_action()


def get_object_list_action():
    return prod_object_list_action()
