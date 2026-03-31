import os
import subprocess

import pytest

from tests.conftest import PROJ_ROOT


def _enabled() -> bool:
    return os.getenv("DOA_CUNIT", "0").strip().lower() in {"1", "true", "yes", "on"}


@pytest.mark.doa_cunit
def test_doa_cunit_ctest_bridge() -> None:
    if not _enabled():
        pytest.skip("set DOA_CUNIT=1 to enable C unit bridge test")

    build_dir = PROJ_ROOT / "build_doa_tests"

    configure = subprocess.run(
        ["cmake", "-S", "modules/fph/doa/tests", "-B", str(build_dir)],
        cwd=PROJ_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert configure.returncode == 0, configure.stdout + "\n" + configure.stderr

    build = subprocess.run(
        ["cmake", "--build", str(build_dir), "-j"],
        cwd=PROJ_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stdout + "\n" + build.stderr

    ctest = subprocess.run(
        ["ctest", "--test-dir", str(build_dir), "--output-on-failure"],
        cwd=PROJ_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert ctest.returncode == 0, ctest.stdout + "\n" + ctest.stderr
