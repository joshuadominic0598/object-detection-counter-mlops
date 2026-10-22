"""Container lifecycle selected by the same DATABASE_BACKEND as the app.

Uses only the Python standard library so startup needs no host ML packages.
Compose reads .env and gives shell overrides their usual precedence.
"""

import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ["docker", "compose", "--project-directory", str(ROOT)]


def run(arguments, **kwargs):
    return subprocess.run(BASE + arguments, check=True, **kwargs)


def image_exists(image):
    result = subprocess.run(
        ["docker", "image", "inspect", image], capture_output=True, text=True,
    )
    if result.returncode == 0:
        return True
    if "no such image" in result.stderr.lower() or "no such object" in result.stderr.lower():
        return False
    raise ValueError(f"Cannot inspect the local API image: {result.stderr.strip()}")


def main(arguments):
    if not (ROOT / ".env").exists():
        shutil.copyfile(ROOT / ".env.example", ROOT / ".env")
        print(".env created from .env.example", flush=True)
    command = arguments[0] if arguments else "start"
    if command == "stop":
        # Also works after an invalid backend value has been entered in .env.
        run(["--profile", "mongodb", "stop", "api", "mongo"])
        return
    config = json.loads(run(["config", "--format", "json"], capture_output=True, text=True).stdout)
    environment = config["services"]["api"]["environment"]
    backend = environment["DATABASE_BACKEND"].strip().lower()
    if backend not in {"mongodb", "sqlite"}:
        raise ValueError("DATABASE_BACKEND must be 'mongodb' or 'sqlite'")
    profile = ["--profile", backend]
    if command == "build":
        run(profile + ["build", "api"])
        return
    if command in {"setup", "start"}:
        image = config["services"]["api"]["image"]
        if image_exists(image):
            print(f"Using cached API image: {image} (runtime source is mounted; run make build after dependency changes)", flush=True)
        else:
            run(profile + ["build", "api"])
        for directory in ("tmp", "results", "tmp/models"):
            (ROOT / directory).mkdir(parents=True, exist_ok=True)
        if environment.get("MODEL_PATH"):
            run(profile + ["run", "--rm", "--no-deps", "api", "python", "-c",
                "import os; from pathlib import Path; from ultralytics import YOLO; "
                "p=os.environ['MODEL_PATH']; Path(p).parent.mkdir(parents=True, exist_ok=True); YOLO(p)"])
        else:
            run(profile + ["run", "--rm", "--no-deps", "api", "python", "scripts/download_model.py", "--active"])
        run(["--profile", "mongodb", "stop", "api", "mongo"])
        if backend == "mongodb":
            run(profile + ["up", "-d", "--wait", "--wait-timeout", "120", "mongo"])
        def enabled(name):
            return str(environment.get(name, "false")).lower() in {"true", "yes", "1", "on"}
        if command == "start" and (
            enabled("CLEAR_DATABASE_ON_START") or (backend == "mongodb" and enabled("CLEAR_MONGO_DB"))
        ):
            run(profile + ["run", "--rm", "--no-deps", "api", "python", "scripts/reset_database.py"])
        if command == "start" and enabled("CLEAR_MODEL_REGISTRY"):
            run(profile + ["run", "--rm", "--no-deps", "api", "python", "-m",
                "model_management.model_registry.registry", "reset", "--yes"])
        run(profile + ["up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "180", "api"])
        print(f"App + API ready using {backend}: http://localhost:{config['services']['api']['ports'][0]['published']} (API docs: /docs)")
    elif command == "python":
        run(profile + ["run", "--rm", "--no-deps", "api", "python"] + arguments[1:])
    elif command == "exec":
        run(profile + ["exec", "-T", "api", "python"] + arguments[1:])
    else:
        raise ValueError("Usage: containers.py setup|start|build|stop|python <args>|exec <args>")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (ValueError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
