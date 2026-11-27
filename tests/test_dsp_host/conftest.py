"""Pytest fixtures and helpers for DSP host tests."""
import subprocess
import time
from pathlib import Path
import numpy as np
import pytest

TEST_DIR = Path(__file__).parent
STIMULI_DIR = TEST_DIR / "stimuli"
BASELINE_DIR = TEST_DIR / "baselines"
REPO_ROOT = TEST_DIR.parent.parent
BUILD_HOST_DIR = REPO_ROOT / "build-host"

DEFAULT_BINARY = (
    BUILD_HOST_DIR
    / "examples" / "bare-metal" / "pipeline_single_threaded" / "bin"
    / "fwk_voice_example_bare_metal_pipeline_single_thread"
)


def pytest_addoption(parser):
    parser.addoption(
        "--dsp-binary",
        action="store",
        default=None,
        help="Path to the DSP pipeline test binary",
    )


@pytest.fixture(scope="session")
def pipeline_binary(request):
    """Return path to the built pipeline binary."""
    path = request.config.getoption("--dsp-binary")
    if path:
        path = Path(path)
    else:
        path = DEFAULT_BINARY
    if not path.exists():
        pytest.fail(
            f"Pipeline binary not found at {path}.\n"
            f"Build it with: bash tools/build_dsp_host.sh\n"
            f"Or pass --dsp-binary /path/to/binary"
        )
    return path


@pytest.fixture(scope="session")
def output_dir(tmp_path_factory):
    """Temp directory for output WAVs."""
    d = tmp_path_factory.mktemp("dsp_output")
    return d


def run_pipeline(binary, stimulus_path, output_path):
    """Run the pipeline binary. Returns elapsed time in seconds."""
    start = time.time()
    result = subprocess.run(
        [str(binary), str(stimulus_path), str(output_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    elapsed = time.time() - start
    if result.returncode != 0:
        raise RuntimeError(
            f"Pipeline failed (rc={result.returncode})\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return elapsed


def read_wav_32bit(path):
    """Load WAV as int32 numpy array. Returns (data, sample_rate)."""
    from scipy.io import wavfile
    sr, data = wavfile.read(str(path))
    assert data.dtype == np.int32, f"Expected int32, got {data.dtype}"
    return data, sr


def read_wav_float(path):
    """Load WAV as float32 in [-1, 1]. Returns (data, sample_rate)."""
    data, sr = read_wav_32bit(path)
    return data.astype(np.float32) / 32768.0, sr
