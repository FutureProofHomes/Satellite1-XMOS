"""Layer 1: Binary gates. Any failure = CI is red."""
import sys
from pathlib import Path
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import STIMULI_DIR, run_pipeline, read_wav_float, read_wav_32bit
from metrics import rms_db, clipping_ratio

# The DSP pipeline uses int32 with 16-bit equivalent full scale (32768).
# AGC normalizes output to approximately +15 to +20 dBFS (16-bit reference).
AGC_TARGET_LOW = 10.0   # dBFS
AGC_TARGET_HIGH = 25.0  # dBFS


class TestDSPGates:
    """7 binary pass/fail gates."""

    def test_g1_pipeline_produces_output(self, pipeline_binary, output_dir):
        """G1: Pipeline produces non-silent output."""
        out_path = output_dir / "g1_out.wav"
        run_pipeline(pipeline_binary, STIMULI_DIR / "speech_clean.wav", out_path)
        data, _ = read_wav_float(out_path)
        level = rms_db(data[:, 0])
        assert level > -60, f"G1 FAIL: output RMS {level:.1f} dBFS (expected > -60)"

    def test_g2_no_overflow(self, pipeline_binary, output_dir):
        """G2: No int32 overflow on loud input."""
        out_path = output_dir / "g2_out.wav"
        run_pipeline(pipeline_binary, STIMULI_DIR / "speech_loud.wav", out_path)
        data, _ = read_wav_32bit(out_path)
        max_val = np.max(np.abs(data))
        # int32 overflow would be >= 2^30 (well into the upper bits)
        assert max_val < 2**30, f"G2 FAIL: near-overflow detected (max={max_val:,})"

    def test_g3_aec_produces_output(self, pipeline_binary, output_dir):
        """G3: Pipeline handles echo input and produces non-silent output."""
        out_path = output_dir / "g3_out.wav"
        run_pipeline(pipeline_binary, STIMULI_DIR / "speech_echo.wav", out_path)
        out_data, _ = read_wav_float(out_path)
        level = rms_db(out_data[:, 0])
        assert level > -30, f"G3 FAIL: echo input produced silent output ({level:.1f} dBFS)"

    def test_g4_ns_produces_output(self, pipeline_binary, output_dir):
        """G4: Pipeline produces non-silent output for noisy input."""
        out_path = output_dir / "g4_out.wav"
        run_pipeline(pipeline_binary, STIMULI_DIR / "speech_babble.wav", out_path)
        out_data, _ = read_wav_float(out_path)
        level = rms_db(out_data[:, 0])
        assert level > -30, f"G4 FAIL: output too quiet ({level:.1f} dBFS)"

    def test_g5_agc_normalizes(self, pipeline_binary, output_dir):
        """G5: AGC output in expected level range."""
        out_path = output_dir / "g5_out.wav"
        run_pipeline(pipeline_binary, STIMULI_DIR / "speech_clean.wav", out_path)
        data, _ = read_wav_float(out_path)
        # Skip first 20 frames for AGC convergence
        skip = 20 * 240
        level = rms_db(data[skip:, 0])
        assert AGC_TARGET_LOW < level < AGC_TARGET_HIGH, (
            f"G5 FAIL: AGC output {level:.1f} dBFS "
            f"(expected in [{AGC_TARGET_LOW}, {AGC_TARGET_HIGH}])"
        )

    def test_g6_no_excessive_clipping(self, pipeline_binary, output_dir):
        """G6: No samples in the top 5 bits of int32 (true overflow territory)."""
        out_path = output_dir / "g6_out.wav"
        run_pipeline(pipeline_binary, STIMULI_DIR / "speech_loud.wav", out_path)
        data, _ = read_wav_32bit(out_path)
        # True clipping in this pipeline = values above 2^28 (top 3 bits set)
        threshold = 2**28
        clip_count = np.sum(np.abs(data) >= threshold)
        clip_ratio = clip_count / data.size
        assert clip_ratio < 0.001, (
            f"G6 FAIL: clipping ratio {clip_ratio*100:.3f}% "
            f"(expected < 0.1%, threshold={threshold:,})"
        )

    def test_g7_silence_stays_quiet(self, pipeline_binary, output_dir):
        """G7: Silence input produces silent output."""
        out_path = output_dir / "g7_out.wav"
        run_pipeline(pipeline_binary, STIMULI_DIR / "silence.wav", out_path)
        data, _ = read_wav_float(out_path)
        level = rms_db(data[:, 0])
        assert level < -40, f"G7 FAIL: silence output {level:.1f} dBFS (expected < -40)"
