"""Layer 2: Regression delta vs. baselines."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import STIMULI_DIR, BASELINE_DIR, run_pipeline, read_wav_float
from metrics import log_mel_distance

STIMULI = sorted(STIMULI_DIR.glob("*.wav"))
PASS_THRESHOLD = 3.0
WARN_THRESHOLD = 6.0


class TestDSPRegression:
    """Output must not change more than 3 dB from baseline."""

    @pytest.mark.skipif(not STIMULI, reason="No stimuli found")
    @pytest.mark.skipif(not list(BASELINE_DIR.glob("*.wav")), reason="No baselines found")
    def test_regression(self, pipeline_binary, output_dir):
        for stim in STIMULI:
            baseline_path = BASELINE_DIR / f"{stim.stem}_baseline.wav"
            if not baseline_path.exists():
                pytest.skip(f"No baseline for {stim.name}")

            out_path = output_dir / f"{stim.stem}_out.wav"
            run_pipeline(pipeline_binary, stim, out_path)
            new_data, _ = read_wav_float(out_path)
            base_data, _ = read_wav_float(baseline_path)

            dist = log_mel_distance(new_data[:, 0], base_data[:, 0])

            if dist > WARN_THRESHOLD:
                pytest.fail(
                    f"REGRESSION: {stim.stem} changed {dist:.2f} dB from baseline "
                    f"(threshold: {PASS_THRESHOLD} dB)"
                )
            elif dist > PASS_THRESHOLD:
                print(f"\nWARNING: {stim.stem} changed {dist:.2f} dB from baseline")
