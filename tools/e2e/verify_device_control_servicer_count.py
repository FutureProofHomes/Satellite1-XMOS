#!/usr/bin/env python3

from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[2]

CONFIG_HEADER = (
    REPO / "satellite-xmos-firmware/src/control/device_control_servicer_config.h"
)
MAIN_C = REPO / "satellite-xmos-firmware/src/main.c"
SQ66_PLATFORM_INIT = (
    REPO / "satellite-xmos-firmware/bsp_config/XK-VOICE-SQ66/platform/platform_init.c"
)
SAT1_PLATFORM_INIT = (
    REPO / "satellite-xmos-firmware/bsp_config/SATELLITE1/platform/platform_init.c"
)


def _check_contains(path: Path, token: str) -> str | None:
    text = path.read_text(encoding="utf-8")
    if token not in text:
        return f"missing `{token}` in {path}"
    return None


def main() -> int:
    errors: list[str] = []

    checks = [
        (CONFIG_HEADER, "APP_DEVICE_CTRL_TOTAL_SERVICER_COUNT"),
        (CONFIG_HEADER, "appconfAUDIO_CFG_SERVICER_COMPAT_ENABLED"),
        (MAIN_C, "#if appconfAUDIO_CFG_SERVICER_COMPAT_ENABLED"),
        (SQ66_PLATFORM_INIT, "APP_DEVICE_CTRL_TOTAL_SERVICER_COUNT"),
        (SAT1_PLATFORM_INIT, "APP_DEVICE_CTRL_TOTAL_SERVICER_COUNT"),
    ]

    for path, token in checks:
        err = _check_contains(path, token)
        if err is not None:
            errors.append(err)

    if errors:
        for err in errors:
            print(f"ERROR: {err}")
        return 1

    print("OK: device-control servicer-count configuration is centralized and wired")
    return 0


if __name__ == "__main__":
    sys.exit(main())
