import os
import subprocess

import pytest

from tests.conftest import SAT1_HIL_ENABLED


@pytest.fixture(scope="session")
def require_sat1_hil() -> None:
    if not SAT1_HIL_ENABLED:
        pytest.skip("Satellite1 HIL tests disabled (set SAT1_HIL=1 to enable)")


@pytest.fixture(scope="session")
def sat1_rpi_host(require_sat1_hil: None) -> str:
    host = os.getenv("SAT1_RPI_HOST", "").strip()
    if not host:
        pytest.skip(
            "SAT1_RPI_HOST is not set (source tools/env/xmos_env.sh to load .env)"
        )
    return host


@pytest.fixture(scope="session")
def sat1_rpi_sat1_cmd(sat1_rpi_host: str) -> str:
    requested = os.getenv("SAT1_RPI_CLI_CMD", "sat1").strip() or "sat1"
    candidates = [requested]
    if requested == "sat1":
        candidates.extend(
            [
                "/home/pi/.cache/venvs/satellite1-rpi-e2e/bin/sat1",
                "/opt/satellite1/venv/bin/sat1",
            ]
        )

    for cmd in candidates:
        proc = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                sat1_rpi_host,
                f"{cmd} xmos get-mic-pipeline-settings -h",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if proc.returncode == 0:
            return cmd

    pytest.skip(
        "No SAT1 CLI with mic-pipeline commands found. Set SAT1_RPI_CLI_CMD "
        "to a deployed CLI path on the Pi host."
    )


@pytest.fixture(scope="session")
def sat1_rpi_py_cmd() -> str:
    return (
        os.getenv("SAT1_RPI_PY_CMD", "/opt/satellite1/venv/bin/python").strip()
        or "/opt/satellite1/venv/bin/python"
    )
