import os
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent
SAT1_FIRMWARE_SRC = PROJ_ROOT / "satellite-xmos-firmware"


def _env_flag(name: str, default: str = "0") -> bool:
    value = os.getenv(name, default).strip().lower()
    return value in {"1", "true", "yes", "on"}


HW_TESTS = os.getenv("HW_TESTS")
SQ66_HIL_ENABLED = _env_flag("SQ66_HIL")
