import os
import subprocess
import time
from pathlib import Path
from typing import Iterator

import pytest

from tests.conftest import PROJ_ROOT, SQ66_HIL_ENABLED

_default_runner = PROJ_ROOT / "tools" / "e2e" / "run_sq66_dev.sh"
RUNNER = Path(os.getenv("SQ66_RUNNER", str(_default_runner)))


def _env_flag(name: str, default: str = "0") -> bool:
    value = os.getenv(name, default).strip().lower()
    return value in {"1", "true", "yes", "on"}


@pytest.fixture(scope="session")
def require_sq66_hil() -> None:
    if not SQ66_HIL_ENABLED:
        pytest.skip("SQ66 HIL tests disabled (set SQ66_HIL=1 to enable)")


@pytest.fixture(scope="session")
def sq66_adapter_id() -> str | None:
    adapter = os.getenv("XMOS_ADAPTER_ID")
    return adapter.strip() if adapter else None


@pytest.fixture(scope="session")
def sq66_rpi_host(require_sq66_hil: None) -> str:
    host = os.getenv("SQ66_RPI_HOST", "").strip()
    if not host:
        pytest.skip("SQ66_RPI_HOST is not set")
    return host


@pytest.fixture(scope="session")
def sq66_rpi_sat1_cmd() -> str:
    return os.getenv("SQ66_RPI_SAT1_CMD", "sat1").strip() or "sat1"


@pytest.fixture(scope="session")
def sq66_runner_proc(
    require_sq66_hil: None, sq66_adapter_id: str | None
) -> Iterator[subprocess.Popen[str] | None]:
    if not _env_flag("SQ66_HIL_RUN_FIRMWARE"):
        yield None
        return

    cmd = [str(RUNNER), "--run", "--skip-build"]
    if sq66_adapter_id:
        cmd += ["--adapter-id", sq66_adapter_id]

    proc = subprocess.Popen(
        cmd,
        cwd=PROJ_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    boot_wait_s = float(os.getenv("SQ66_HIL_BOOT_WAIT_S", "8"))
    time.sleep(boot_wait_s)

    if proc.poll() is not None:
        out = ""
        if proc.stdout:
            out = proc.stdout.read()
        pytest.fail(f"SQ66 firmware runner exited early (rc={proc.returncode}):\n{out}")

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


@pytest.fixture(scope="session")
def ensure_sq66_running(sq66_runner_proc: subprocess.Popen[str] | None) -> None:
    if sq66_runner_proc is None and _env_flag("SQ66_HIL_REQUIRE_RUNNER"):
        pytest.skip(
            "SQ66_HIL_REQUIRE_RUNNER=1 but SQ66_HIL_RUN_FIRMWARE is not enabled"
        )
