"""Opt-in SQ66 xTAG discovery smoke test; no firmware lifecycle actions."""

import os
import subprocess

import pytest

from tests.conftest import PROJ_ROOT


RUNNER = PROJ_ROOT / "tools/e2e/run_sq66_detect_only.sh"


def test_sq66_detect_only_reports_adapter() -> None:
    if os.getenv("SQ66_HIL") != "1":
        pytest.skip("set SQ66_HIL=1 to enable SQ66 xTAG discovery")

    result = subprocess.run(
        ["bash", str(RUNNER), "--detect-only"],
        cwd=PROJ_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    for field in ("mode=run", "build_dir=", "target=", "adapter_id="):
        assert field in result.stdout
