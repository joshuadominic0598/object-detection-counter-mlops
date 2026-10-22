from pathlib import Path
import os
import subprocess
import sys
import threading
import time

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from counter import config
from counter.adapters.detection.roboflow_detector import RoboflowDetector, RoboflowError, RoboflowOptions
from counter.application.detection import DetectionService
from counter.entrypoints.image_uploads import MAX_UPLOAD_BYTES, RequestSizeLimit, canonical_image, validate_session

ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).with_name("static")
SAMPLES = {path.name: path for path in sorted((ROOT / "resources/images").iterdir())
           if path.suffix.lower() in {".png", ".jpeg", ".jpg", ".webp"}}


def parse_bool(value):
    normalized = str(value).strip().lower()
    if normalized in {"true", "false"}:
        return normalized == "true"
    raise HTTPException(status_code=400, detail="counter must be 'true' or 'false'")


def roboflow_detector(api_key, mode, workspace, workflow_id, model_id, output_path):
    try:
        return RoboflowDetector(RoboflowOptions(
            api_key=api_key or os.getenv("ROBOFLOW_API_KEY", ""), mode=mode,
            workspace=workspace, workflow_id=workflow_id, model_id=model_id, output_path=output_path))
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


def create_app():
    app = FastAPI(title="Object Counter", version="2.0")
    app.add_middleware(RequestSizeLimit)
    repo = config.get_repo()
    service = DetectionService(config.get_detector, repo, config.get_monitor())
    dashboard_lock = threading.Lock()

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        # Browser mutations must originate from this app. No CORS or remote file/URL inputs.
        origin = request.headers.get("origin")
        if request.method == "POST" and origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
            return JSONResponse({"detail": "Cross-origin requests are not allowed."}, 403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(status_code=400, content={"detail": "Missing or invalid form fields. Check session, threshold and image."})

    @app.get("/health")
    def health():
        repo.read_values("__health__")
        return {"status": "ok"}

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/api/status")
    def status():
        repo.read_values("__health__")
        return {"status": "ok", "local_model": Path(config.MODEL_PATH).name,
                "server_key_available": bool(os.getenv("ROBOFLOW_API_KEY")),
                "roboflow": {"workspace": "model-version2", "workflow_id": "parking-detection-v3-logic"},
                "limits": {"image_mb": 10, "megapixels": 16, "max_dimension": 8192, "batch_size": 20}}

    @app.get("/api/samples")
    def samples():
        return [{"id": name, "name": Path(name).stem.replace("_", " "), "url": f"/api/samples/{name}"}
                for name in SAMPLES]

    @app.get("/api/samples/{sample_id}")
    def sample(sample_id: str):
        if sample_id not in SAMPLES:
            raise HTTPException(404, "Sample not found.")
        return FileResponse(SAMPLES[sample_id])

    @app.get("/api/results/{session_id}/{filename}")
    def result_image(session_id: str, filename: str):
        validate_session(session_id)
        directory = (ROOT / "results" / session_id).resolve()
        path = (directory / filename).resolve()
        if path.parent != directory or path.suffix != ".jpg" or not path.is_file():
            raise HTTPException(404, "Result not found.")
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/api/sessions/{session_id}")
    def session(session_id: str):
        validate_session(session_id)
        return {"session_id": session_id, "total_counts": {v.object_class: v.count for v in repo.read_values(session_id)}}

    def generate_dashboards():
        with dashboard_lock:
            for script in ("generate_monitoring_dashboard.py", "generate_session_dashboard.py"):
                try:
                    subprocess.run([sys.executable, str(ROOT / "monitoring" / script)], cwd=ROOT,
                                   capture_output=True, check=True, timeout=60)
                except (subprocess.SubprocessError, OSError):
                    raise HTTPException(503, "Dashboard generation failed. Check storage and retry.") from None

    @app.get("/dashboards/{filename}")
    def dashboard(filename: str):
        if filename not in {"monitoring_dashboard.html", "session_dashboard.html"}:
            raise HTTPException(404, "Dashboard not found.")
        generate_dashboards()
        return FileResponse(ROOT / "tmp/dashboard" / filename)

    @app.post("/api/roboflow/test-connection")
    def test_roboflow_connection(
        roboflow_mode: str = Form("model"), api_key: str = Form(""),
        workspace_name: str = Form("model-version2"), workflow_id: str = Form("parking-detection-v3-logic"),
        model_id: str = Form("parking-detection-ewm7h/3"), output_path: str = Form("predictions"),
    ):
        detector = roboflow_detector(api_key, roboflow_mode, workspace_name, workflow_id, model_id, output_path)
        # Verify actual access and compatible detection output without touching sessions,
        # counters, result files or monitoring history. This uses one remote inference.
        started = time.perf_counter()
        image, _ = canonical_image(SAMPLES["carlot.jpeg"].read_bytes())
        try:
            detector.predict(image)
        except RoboflowError as error:
            raise HTTPException(error.status_code, str(error)) from None
        except Exception:
            raise HTTPException(502, "Could not verify this Roboflow deployment. Please try again.") from None
        finally:
            image.close()
        return {"status": "connected", "mode": roboflow_mode,
                "deployment": model_id if roboflow_mode == "model" else f"{workspace_name}/{workflow_id}",
                "latency_ms": round((time.perf_counter() - started) * 1000)}

    async def detect(endpoint, session_id, threshold, counter, file, provider, roboflow_mode,
                     api_key, workspace_name, workflow_id, model_id, output_path):
        validate_session(session_id)
        counter_flag = parse_bool(counter)
        if not 0 <= threshold <= 1:
            raise HTTPException(400, "Confidence threshold must be between 0 and 1.")
        if provider not in {"local", "roboflow"}:
            raise HTTPException(400, "Provider must be local or roboflow.")
        if not file.filename:
            raise HTTPException(400, "Image filename is required.")
        detector = None
        if provider == "roboflow":
            detector = roboflow_detector(api_key, roboflow_mode, workspace_name, workflow_id, model_id, output_path)
        try:
            data = await file.read(MAX_UPLOAD_BYTES + 1)
        finally:
            await file.close()
        image, size = await run_in_threadpool(canonical_image, data)
        # Filenames are display metadata only; all result paths are generated by us.
        image_name = Path(file.filename.replace("\\", "/")).name[:200]
        try:
            return await run_in_threadpool(service.run, image, size, threshold, session_id, counter_flag,
                                          provider, detector, image_name, endpoint)
        except RoboflowError as error:
            raise HTTPException(error.status_code, str(error)) from None
        except Exception:
            raise HTTPException(500, "Detection failed. Check the local model and storage configuration.") from None
        finally:
            image.close()

    @app.post("/api/detect")
    @app.post("/object-detection")
    async def object_detection(
        request: Request,
        session_id: str = Form(...), threshold: float = Form(0.5), counter: str = Form("false"),
        file: UploadFile = File(...), provider: str = Form("local"),
        roboflow_mode: str = Form("workflow"), api_key: str = Form(""),
        workspace_name: str = Form("model-version2"), workflow_id: str = Form("parking-detection-v3-logic"),
        model_id: str = Form(""), output_path: str = Form("predictions"),
    ):
        result = await detect(request.url.path, session_id, threshold, counter, file, provider,
                              roboflow_mode, api_key, workspace_name, workflow_id, model_id, output_path)
        if request.url.path == "/object-detection":
            if result["counter"]:
                def objects(values):
                    return [{"object_class": name, "count": number} for name, number in values.items()]
                return {"current_objects": objects(result["counts"]), "total_objects": objects(result["total_counts"])}
            return result["predictions"]
        return result

    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host="0.0.0.0", port=5000)
