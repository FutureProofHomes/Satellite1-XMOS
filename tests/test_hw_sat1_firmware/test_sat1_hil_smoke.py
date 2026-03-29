import os
import subprocess
import time

import pytest

from tests.conftest import PROJ_ROOT


SSH_CONNECT_TIMEOUT_S = int(os.getenv("SAT1_HIL_SSH_CONNECT_TIMEOUT_S", "5"))
SSH_CMD_TIMEOUT_S = int(os.getenv("SAT1_HIL_SSH_TIMEOUT_S", "20"))
RETRY_ATTEMPTS = int(os.getenv("SAT1_HIL_RETRY_ATTEMPTS", "4"))
RETRY_DELAY_S = float(os.getenv("SAT1_HIL_RETRY_DELAY_S", "0.5"))
SCRIPT_TIMEOUT_S = int(os.getenv("SAT1_HIL_FLASH_VERIFY_TIMEOUT_S", "90"))
SAT1_FLASH_SCRIPT = PROJ_ROOT / "tools" / "e2e" / "run_sat1_flash_via_rpi.sh"


def _run_local(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=PROJ_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _run_ssh(
    host: str, cmd: str, timeout: int = SSH_CMD_TIMEOUT_S
) -> subprocess.CompletedProcess[str]:
    return _run_local(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={SSH_CONNECT_TIMEOUT_S}",
            host,
            cmd,
        ],
        timeout=timeout,
    )


def _run_ssh_with_retry(
    host: str,
    cmd: str,
    *,
    attempts: int = RETRY_ATTEMPTS,
    delay_s: float = RETRY_DELAY_S,
    timeout: int = SSH_CMD_TIMEOUT_S,
) -> subprocess.CompletedProcess[str]:
    last: subprocess.CompletedProcess[str] | None = None
    for idx in range(attempts):
        last = _run_ssh(host, cmd, timeout=timeout)
        out = last.stdout.strip()
        if last.returncode == 0 and out and out != "None":
            return last
        if idx < attempts - 1:
            time.sleep(delay_s)
    assert last is not None
    return last


def _can_set_and_read_dac_volume(host: str, sat1_cmd: str, dac: str) -> bool:
    vol_set = _run_ssh(host, f"{sat1_cmd} dac --dac {dac} set-volume 0.40")
    if vol_set.returncode != 0:
        return False

    vol_get = _run_ssh(host, f"{sat1_cmd} dac --dac {dac} volume")
    if vol_get.returncode != 0:
        return False

    return bool(vol_get.stdout.strip())


@pytest.mark.hil
@pytest.mark.sat1
def test_sat1_cli_reads_firmware_and_status(
    require_sat1_hil: None,
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
) -> None:
    fw = _run_ssh_with_retry(sat1_rpi_host, f"{sat1_rpi_sat1_cmd} xmos read-firmware")
    assert fw.returncode == 0, fw.stdout + fw.stderr
    assert fw.stdout.strip() and fw.stdout.strip() != "None", (
        "Expected firmware version output"
    )

    status = _run_ssh_with_retry(sat1_rpi_host, f"{sat1_rpi_sat1_cmd} xmos read-status")
    assert status.returncode == 0, status.stdout + status.stderr
    assert status.stdout.strip() and status.stdout.strip() != "None", (
        "Expected xmos status output"
    )


@pytest.mark.hil
@pytest.mark.sat1
def test_sat1_cli_dac_setup_and_volume(
    require_sat1_hil: None,
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
) -> None:
    setup = _run_ssh(sat1_rpi_host, f"{sat1_rpi_sat1_cmd} dac setup", timeout=60)
    assert setup.returncode == 0, setup.stdout + setup.stderr

    for dac in ("speaker", "line-out"):
        if _can_set_and_read_dac_volume(sat1_rpi_host, sat1_rpi_sat1_cmd, dac):
            return

    pytest.fail(
        "Failed to set/read DAC volume for both speaker and line-out on Satellite1"
    )


@pytest.mark.hil
@pytest.mark.sat1
def test_sat1_flash_script_verify_mode(
    require_sat1_hil: None,
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
) -> None:
    if not SAT1_FLASH_SCRIPT.exists():
        pytest.fail(f"Satellite1 flash script not found: {SAT1_FLASH_SCRIPT}")

    res = _run_local(
        [
            str(SAT1_FLASH_SCRIPT),
            "--verify",
            "--rpi-host",
            sat1_rpi_host,
            "--sat1-cmd",
            sat1_rpi_sat1_cmd,
        ],
        timeout=SCRIPT_TIMEOUT_S,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "verified_firmware=" in res.stdout, res.stdout + res.stderr
