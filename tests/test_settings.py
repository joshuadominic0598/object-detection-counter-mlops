import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("backend", ["sqlite", "mongodb"])
def test_config_selects_matching_adapters(backend, tmp_path):
    code = """
from counter import config, settings
from counter.domain.ports import ObjectCountRepo, Monitor, MonitoringReader
assert isinstance(config.get_repo(), ObjectCountRepo)
assert isinstance(config.get_monitor(), Monitor)
assert isinstance(settings.get_monitoring_reader(), MonitoringReader)
assert ('SQLite' in type(config.get_repo()).__name__) == (settings.DATABASE_BACKEND == 'sqlite')
assert ('SQLite' in type(config.get_monitor()).__name__) == (settings.DATABASE_BACKEND == 'sqlite')
"""
    subprocess.run([sys.executable, "-c", code], check=True, env={
        **os.environ, "DATABASE_BACKEND": backend, "SQLITE_PATH": str(tmp_path / "counter.sqlite3"),
    })


def test_invalid_backend_fails_before_app_starts():
    result = subprocess.run([sys.executable, "-c", "import counter.settings"],
        capture_output=True, text=True, env={**os.environ, "DATABASE_BACKEND": "unsupported"})
    assert result.returncode != 0
    assert "DATABASE_BACKEND must be 'mongodb' or 'sqlite'" in result.stderr
