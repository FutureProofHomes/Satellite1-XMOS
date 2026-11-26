"""Bit-exact fractional steering, including the actual XS3A divide instruction."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "satellite-xmos-firmware/src"


@pytest.mark.parametrize("backend", ["host", "xcore"])
def test_beamformer_math(tmp_path, backend):
    compiler = shutil.which("xcc" if backend == "xcore" else "cc")
    if not compiler or (backend == "xcore" and not shutil.which("xsim")):
        pytest.skip(f"The {backend} compiler/simulator is required")

    # Run the full production frame/state handling with only its interpolation
    # replaced by the frozen arithmetic. No reference dependence on Git HEAD.
    source = (SRC / "beamforming/sat1_beamformer.c").read_text()
    start = source.index("static int32_t fractional_delay_sample(")
    end = source.index("\nstatic uint32_t frame_mean_abs(", start)
    reference = (ROOT / "tests/beamformer_reference.h").read_text().replace(
        "reference_fractional_delay_sample", "fractional_delay_sample")
    source = source[:start] + reference + "\n" + source[end:]
    names = re.findall(r"^void (sat1_beamformer_\w+)\(", source, re.M)
    reference_source = tmp_path / "reference.c"
    reference_source.write_text(
        "".join(f"#define {name} reference_{name}\n" for name in names) + source)
    binary = tmp_path / ("math.xe" if backend == "xcore" else "math")
    flags = (["-target=XCORE-AI-EXPLORER", "-Os", "-g", "-mcmodel=large"]
             if backend == "xcore" else
             ["-std=c11", "-O1", "-fsanitize=undefined,address", "-fno-sanitize-recover=all"])
    subprocess.run([compiler, *flags, "-Wall", "-Wextra", "-Werror",
                    "-Wno-unused-function", "-I", str(SRC),
                    "-I", str(SRC / "beamforming"),
                    str(ROOT / "tests/test_sat1_beamformer_math.c"),
                    str(reference_source), "-o", str(binary)], check=True, timeout=60)
    subprocess.run((["xsim"] if backend == "xcore" else []) + [str(binary)],
                   check=True, timeout=600)
