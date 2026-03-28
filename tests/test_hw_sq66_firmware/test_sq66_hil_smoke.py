import os
import subprocess
import time

import pytest

from tests.conftest import PROJ_ROOT


SSH_CONNECT_TIMEOUT_S = int(os.getenv("SQ66_HIL_SSH_CONNECT_TIMEOUT_S", "5"))
SSH_CMD_TIMEOUT_S = int(os.getenv("SQ66_HIL_SSH_TIMEOUT_S", "20"))
RETRY_ATTEMPTS = int(os.getenv("SQ66_HIL_RETRY_ATTEMPTS", "4"))
RETRY_DELAY_S = float(os.getenv("SQ66_HIL_RETRY_DELAY_S", "0.5"))


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


@pytest.mark.hil
@pytest.mark.sq66
def test_sq66_detect_only_reports_adapter(
    require_sq66_hil: None, sq66_adapter_id: str | None
) -> None:
    runner = os.getenv("SQ66_RUNNER", "tools/e2e/run_sq66_dev.sh")
    if not os.path.exists(runner):
        pytest.skip(f"SQ66 runner not found: {runner}")

    cmd = [runner, "--detect-only"]
    if sq66_adapter_id:
        cmd += ["--adapter-id", sq66_adapter_id]

    result = _run_local(cmd, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert "mode=run" in out
    assert "build_dir=" in out
    assert "target=" in out
    assert "adapter_id=" in out


@pytest.mark.hil
@pytest.mark.sq66
def test_sq66_cli_reads_firmware_and_status(
    require_sq66_hil: None,
    ensure_sq66_running: None,
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
) -> None:
    fw = _run_ssh_with_retry(
        sq66_rpi_host,
        f"{sq66_rpi_sat1_cmd} --board sq66 xmos read-firmware",
    )
    assert fw.returncode == 0, fw.stdout + fw.stderr
    assert fw.stdout.strip() and fw.stdout.strip() != "None", (
        "Expected firmware version output"
    )

    status = _run_ssh_with_retry(
        sq66_rpi_host, f"{sq66_rpi_sat1_cmd} --board sq66 xmos read-status"
    )
    assert status.returncode == 0, status.stdout + status.stderr
    assert status.stdout.strip() and status.stdout.strip() != "None", (
        "Expected xmos status output"
    )


@pytest.mark.hil
@pytest.mark.sq66
def test_sq66_cli_enforces_lineout_only(
    require_sq66_hil: None,
    ensure_sq66_running: None,
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
) -> None:
    spk = _run_ssh(
        sq66_rpi_host, f"{sq66_rpi_sat1_cmd} --board sq66 dac --dac speaker volume"
    )
    assert spk.returncode != 0
    msg = (spk.stdout + spk.stderr).lower()
    assert "speaker dac not available on sq66" in msg


@pytest.mark.hil
@pytest.mark.sq66
def test_sq66_cli_lineout_setup_and_volume(
    require_sq66_hil: None,
    ensure_sq66_running: None,
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
) -> None:
    setup = _run_ssh(
        sq66_rpi_host, f"{sq66_rpi_sat1_cmd} --board sq66 dac setup", timeout=60
    )
    assert setup.returncode == 0, setup.stdout + setup.stderr

    vol_set = _run_ssh(
        sq66_rpi_host,
        f"{sq66_rpi_sat1_cmd} --board sq66 dac --dac line-out set-volume 0.40",
    )
    assert vol_set.returncode == 0, vol_set.stdout + vol_set.stderr

    vol_get = _run_ssh(
        sq66_rpi_host, f"{sq66_rpi_sat1_cmd} --board sq66 dac --dac line-out volume"
    )
    assert vol_get.returncode == 0, vol_get.stdout + vol_get.stderr
    out = vol_get.stdout.strip()
    assert out, "Expected non-empty line-out volume output"


@pytest.mark.hil
@pytest.mark.sq66
def test_sq66_cli_plugged_in_reports_unsupported(
    require_sq66_hil: None,
    ensure_sq66_running: None,
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
) -> None:
    cmd = f"{sq66_rpi_sat1_cmd} --board sq66 dac plugged-in"
    res = _run_ssh(sq66_rpi_host, cmd)
    assert res.returncode != 0
    msg = (res.stdout + res.stderr).lower()
    assert "line-out jack detect not available on sq66" in msg
