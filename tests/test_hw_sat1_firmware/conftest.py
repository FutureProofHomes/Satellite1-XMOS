import os

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
def sat1_rpi_sat1_cmd() -> str:
    return os.getenv("SAT1_RPI_SAT1_CMD", "sat1").strip() or "sat1"


@pytest.fixture(scope="session")
def sat1_rpi_py_cmd() -> str:
    return (
        os.getenv("SAT1_RPI_PY_CMD", "/opt/satellite1/venv/bin/python").strip()
        or "/opt/satellite1/venv/bin/python"
    )
