"""Exercise the real voice policy on host and XS3A, including signed extremes."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "satellite-xmos-firmware/src"


@pytest.mark.parametrize("backend", ["host", "xcore"])
def test_voice_policy(tmp_path, backend):
    compiler = shutil.which("xcc" if backend == "xcore" else "cc")
    if not compiler or (backend == "xcore" and not shutil.which("xsim")):
        pytest.skip(f"The {backend} compiler/simulator is required")
    binary = tmp_path / ("policy.xe" if backend == "xcore" else "policy")
    flags = (["-target=XCORE-AI-EXPLORER", "-Os", "-g", "-mcmodel=large"]
             if backend == "xcore" else
             ["-std=c11", "-O1", "-fsanitize=undefined,address", "-fno-sanitize-recover=all"])
    subprocess.run([compiler, *flags, "-Wall", "-Wextra", "-Werror", "-I", str(SRC),
                    str(ROOT / "tests/test_sat1_voice_policy.c"),
                    str(SRC / "voice_frontend/sat1_voice_policy.c"),
                    "-o", str(binary)], check=True, timeout=60)
    subprocess.run((["xsim"] if backend == "xcore" else []) + [str(binary)],
                   check=True, timeout=300)
