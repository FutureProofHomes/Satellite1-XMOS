import os
import shlex
import subprocess
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent
SAT1_FIRMWARE_SRC = PROJ_ROOT / "satellite-xmos-firmware"


def _load_xmos_env_for_pytest() -> None:
    if os.getenv("PYTEST_XMOS_ENV_LOADED") == "1":
        return

    env_script = PROJ_ROOT / "tools" / "env" / "xmos_env.sh"
    if not env_script.exists():
        os.environ["PYTEST_XMOS_ENV_LOADED"] = "1"
        return

    cmd = f"source {shlex.quote(str(env_script))} >/dev/null 2>&1 || true; env -0"
    proc = subprocess.run(
        ["bash", "-lc", cmd],
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        os.environ["PYTEST_XMOS_ENV_LOADED"] = "1"
        return

    for entry in proc.stdout.split(b"\x00"):
        if not entry:
            continue
        key, sep, value = entry.partition(b"=")
        if not sep:
            continue
        os.environ[key.decode("utf-8", errors="ignore")] = value.decode(
            "utf-8", errors="ignore"
        )

    os.environ["PYTEST_XMOS_ENV_LOADED"] = "1"


_load_xmos_env_for_pytest()


def _env_flag(name: str, default: str = "0") -> bool:
    value = os.getenv(name, default).strip().lower()
    return value in {"1", "true", "yes", "on"}


HW_TESTS = os.getenv("HW_TESTS")
SQ66_HIL_ENABLED = _env_flag("SQ66_HIL")
SAT1_HIL_ENABLED = _env_flag("SAT1_HIL")
