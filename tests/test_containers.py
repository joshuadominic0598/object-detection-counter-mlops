import json
import subprocess

import pytest

from scripts import containers


@pytest.fixture
def lifecycle(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("DATABASE_BACKEND=mongodb\n")
    monkeypatch.setattr(containers, "ROOT", tmp_path)
    monkeypatch.setattr(containers, "image_exists", lambda image: True)
    calls = []
    environment = {"DATABASE_BACKEND": "sqlite", "MODEL_PATH": "tmp/models/test.pt"}
    def run(arguments, **kwargs):
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, stdout=json.dumps({
            "services": {"api": {"image": "object-counter-api:local", "environment": environment, "ports": [{"published": "5000"}]}}
        }))
    monkeypatch.setattr(containers, "run", run)
    return calls, environment


@pytest.mark.parametrize("backend", ["sqlite", "mongodb"])
def test_start_selects_database_and_stops_previous_stack(lifecycle, backend):
    calls, environment = lifecycle
    environment["DATABASE_BACKEND"] = backend
    containers.main(["start"])
    assert ["--profile", "mongodb", "stop", "api", "mongo"] in calls
    mongo_start = ["--profile", "mongodb", "up", "-d", "--wait", "--wait-timeout", "120", "mongo"]
    assert (mongo_start in calls) == (backend == "mongodb")
    assert calls[-1] == ["--profile", backend, "up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "180", "api"]
    assert not any("build" in call for call in calls)
    assert not any("scripts/reset_database.py" in call for call in calls)


@pytest.mark.parametrize("backend,flag,command,expected", [
    ("sqlite", "CLEAR_MONGO_DB", "start", False),
    ("mongodb", "CLEAR_MONGO_DB", "start", True),
    ("sqlite", "CLEAR_DATABASE_ON_START", "start", True),
    ("mongodb", "CLEAR_DATABASE_ON_START", "start", True),
    ("sqlite", "CLEAR_DATABASE_ON_START", "setup", False),
    ("mongodb", "CLEAR_DATABASE_ON_START", "setup", False),
])
def test_reset_only_on_explicit_selected_backend_flag(lifecycle, backend, flag, command, expected):
    calls, environment = lifecycle
    environment.update({"DATABASE_BACKEND": backend, flag: "true"})
    containers.main([command])
    assert any("scripts/reset_database.py" in call for call in calls) == expected


def test_invalid_backend_never_changes_containers(lifecycle):
    calls, environment = lifecycle
    environment["DATABASE_BACKEND"] = "invalid"
    with pytest.raises(ValueError, match="DATABASE_BACKEND"):
        containers.main(["start"])
    assert calls == [["config", "--format", "json"]]


def test_stop_handles_both_modes(lifecycle):
    calls, _ = lifecycle
    containers.main(["stop"])
    assert calls[-1] == ["--profile", "mongodb", "stop", "api", "mongo"]


def test_missing_api_image_is_built_before_start(lifecycle, monkeypatch):
    calls, _ = lifecycle
    monkeypatch.setattr(containers, "image_exists", lambda image: False)
    containers.main(["start"])
    assert calls[1] == ["--profile", "sqlite", "build", "api"]


def test_explicit_build_does_not_restart_or_reset_services(lifecycle):
    calls, _ = lifecycle
    containers.main(["build"])
    assert calls[1:] == [["--profile", "sqlite", "build", "api"]]


def test_failed_initial_build_leaves_running_stack_alone(lifecycle, monkeypatch):
    calls, _ = lifecycle
    monkeypatch.setattr(containers, "image_exists", lambda image: False)
    original_run = containers.run
    def failed_build(arguments, **kwargs):
        if "build" in arguments:
            raise subprocess.CalledProcessError(1, arguments)
        return original_run(arguments, **kwargs)
    monkeypatch.setattr(containers, "run", failed_build)
    with pytest.raises(subprocess.CalledProcessError):
        containers.main(["start"])
    assert not any("stop" in call or "up" in call for call in calls)


@pytest.mark.parametrize("returncode,stderr,expected", [
    (0, "", True), (1, "Error response from daemon: No such image: demo:local", False),
])
def test_image_inspection_distinguishes_cached_and_missing(monkeypatch, returncode, stderr, expected):
    monkeypatch.setattr(containers.subprocess, "run", lambda *args, **kwargs:
        subprocess.CompletedProcess(args, returncode, stdout="", stderr=stderr))
    assert containers.image_exists("demo:local") is expected


def test_image_inspection_reports_daemon_failure(monkeypatch):
    monkeypatch.setattr(containers.subprocess, "run", lambda *args, **kwargs:
        subprocess.CompletedProcess(args, 1, stdout="", stderr="Cannot connect to the Docker daemon"))
    with pytest.raises(ValueError, match="Cannot connect to the Docker daemon"):
        containers.image_exists("demo:local")
