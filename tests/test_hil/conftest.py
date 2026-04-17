import os
import subprocess

import pytest

from tests.conftest import PROJ_ROOT, SAT1_HIL_ENABLED, SQ66_HIL_ENABLED

I2S_INPUT_MODE_DOWNSAMPLED = 0
I2S_INPUT_MODE_PACKAGED = 1
PIPELINE_TARGET_REF = "ref"
PIPELINE_TARGET_MIC = "mic"


def _enabled_boards() -> list[str]:
    boards: list[str] = []
    if SAT1_HIL_ENABLED:
        boards.append("sat1")
    if SQ66_HIL_ENABLED:
        boards.append("sq66")
    return boards


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "hil_board" in metafunc.fixturenames:
        boards = _enabled_boards()
        if not boards:
            pytest.skip("HIL tests disabled (set SAT1_HIL=1 or SQ66_HIL=1)")
        metafunc.parametrize("hil_board", boards, ids=boards)


@pytest.fixture
def require_hil(hil_board: str) -> None:
    if hil_board == "sat1" and not SAT1_HIL_ENABLED:
        pytest.skip("SAT1 HIL tests disabled (set SAT1_HIL=1 to enable)")
    if hil_board == "sq66" and not SQ66_HIL_ENABLED:
        pytest.skip("SQ66 HIL tests disabled (set SQ66_HIL=1 to enable)")


def _board_env(hil_board: str, suffix: str, default: str | None = None) -> str:
    value = os.getenv(f"{hil_board.upper()}_{suffix}")
    if value is None:
        value = os.getenv(f"{hil_board.upper()}_HIL_{suffix}")
    if value is None:
        value = os.getenv(f"HIL_{suffix}")
    if value is None:
        if default is None:
            return ""
        return default
    return value


def hil_env_str(hil_board: str, suffix: str, default: str) -> str:
    return _board_env(hil_board, suffix, default).strip()


def hil_env_int(hil_board: str, suffix: str, default: int) -> int:
    value = _board_env(hil_board, suffix, str(default)).strip()
    return int(value)


def hil_env_float(hil_board: str, suffix: str, default: float) -> float:
    value = _board_env(hil_board, suffix, str(default)).strip()
    return float(value)


def hil_env_bool(hil_board: str, suffix: str, default: bool) -> bool:
    value = _board_env(hil_board, suffix, "1" if default else "0").strip().lower()
    return value in {"1", "true", "yes", "on"}


@pytest.fixture
def hil_rpi_host(require_hil: None, hil_board: str) -> str:
    host = hil_env_str(hil_board, "RPI_HOST", "")
    if not host:
        pytest.skip(
            f"{hil_board.upper()}_RPI_HOST is not set (source tools/env/xmos_env.sh to load .env)"
        )
    return host


def _probe_cli(host: str, cmd: str) -> bool:
    proc = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            host,
            f"{cmd} xmos get-mic-pipeline-settings -h",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        cwd=PROJ_ROOT,
    )
    return proc.returncode == 0


def _normalize_cli_cmd(hil_board: str, requested: str) -> str:
    cmd = requested.strip()
    if hil_board != "sq66":
        return cmd

    board_flag = "--board sq66"
    if board_flag in cmd:
        return cmd

    return f"{cmd} {board_flag}".strip()


@pytest.fixture
def hil_cli_cmd(hil_rpi_host: str, hil_board: str) -> str:
    if hil_board == "sat1":
        requested = hil_env_str(hil_board, "RPI_CLI_CMD", "sat1")
        candidates = [requested]
        if requested == "sat1":
            candidates.extend(
                [
                    "/home/pi/.cache/venvs/satellite1-rpi-e2e/bin/sat1",
                    "/opt/satellite1/venv/bin/sat1",
                ]
            )
    else:
        requested = hil_env_str(hil_board, "RPI_CLI_CMD", "sat1")
        candidates = [_normalize_cli_cmd(hil_board, requested)]

    for cmd in candidates:
        if _probe_cli(hil_rpi_host, cmd):
            return cmd

    pytest.skip(
        f"No {hil_board.upper()} CLI with mic-pipeline commands found. "
        f"Set {hil_board.upper()}_RPI_CLI_CMD to a deployed CLI path on the Pi host."
    )


@pytest.fixture
def hil_py_cmd(hil_board: str) -> str:
    default = "/opt/satellite1/venv/bin/python"
    return hil_env_str(hil_board, "RPI_PY_CMD", default) or default
