import os
import subprocess
import time
from datetime import datetime
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
def sq66_rpi_sat1_cmd(sq66_rpi_host: str) -> str:
    requested = os.getenv("SQ66_RPI_CLI_CMD", "sat1").strip() or "sat1"
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
                sq66_rpi_host,
                f"{cmd} --board sq66 xmos get-mic-pipeline-settings -h",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if proc.returncode == 0:
            return cmd

    pytest.skip(
        "No SQ66 CLI with mic-pipeline commands found. Set SQ66_RPI_CLI_CMD "
        "to a deployed CLI path on the Pi host."
    )


@pytest.fixture(scope="session")
def sq66_rpi_py_cmd() -> str:
    return (
        os.getenv("SQ66_RPI_PY_CMD", "/opt/satellite1/venv/bin/python").strip()
        or "/opt/satellite1/venv/bin/python"
    )


@pytest.fixture(scope="session")
def sq66_runner_proc(
    require_sq66_hil: None, sq66_adapter_id: str | None
) -> Iterator[subprocess.Popen[str] | None]:
    if not _env_flag("SQ66_HIL_RUN_FIRMWARE"):
        yield None
        return

    run_mode = os.getenv("SQ66_HIL_RUN_MODE", "run").strip().lower() or "run"
    if run_mode not in {"run", "debug"}:
        pytest.fail("SQ66_HIL_RUN_MODE must be 'run' or 'debug'")

    cmd = [str(RUNNER), f"--{run_mode}", "--skip-build"]
    if sq66_adapter_id:
        cmd += ["--adapter-id", sq66_adapter_id]

    xscope_log_path = os.getenv("SQ66_HIL_XSCOPE_LOG", "").strip()
    if not xscope_log_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        xscope_log_path = str(PROJ_ROOT / "build_sq66_dev" / f"sq66_xscope_{ts}.log")
        os.environ["SQ66_HIL_XSCOPE_LOG"] = xscope_log_path
    log_path = Path(xscope_log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8")

    boot_wait_s = float(os.getenv("SQ66_HIL_BOOT_WAIT_S", "8"))
    runner_start_retries = int(os.getenv("SQ66_HIL_RUNNER_START_RETRIES", "3"))
    proc: subprocess.Popen[str] | None = None

    for attempt in range(runner_start_retries):
        proc = subprocess.Popen(
            cmd,
            cwd=PROJ_ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
        time.sleep(boot_wait_s)
        if proc.poll() is None:
            break

        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            pass
        subprocess.run(["pkill", "-f", "xgdbserver"], check=False)
        subprocess.run(["pkill", "-f", "xgdb --batch"], check=False)
        subprocess.run(["pkill", "-f", "xrun --adapter-id"], check=False)
        time.sleep(1.0)
    else:
        log_file.flush()
        out = ""
        try:
            out = log_path.read_text(encoding="utf-8")
        except OSError:
            pass
        log_file.close()
        rc = proc.returncode if proc is not None else "unknown"
        pytest.fail(f"SQ66 firmware runner exited early (rc={rc}):\n{out}")

    assert proc is not None

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    log_file.close()


@pytest.fixture(scope="session")
def ensure_sq66_running(sq66_runner_proc: subprocess.Popen[str] | None) -> None:
    if sq66_runner_proc is None and _env_flag("SQ66_HIL_REQUIRE_RUNNER"):
        pytest.skip(
            "SQ66_HIL_REQUIRE_RUNNER=1 but SQ66_HIL_RUN_FIRMWARE is not enabled"
        )
