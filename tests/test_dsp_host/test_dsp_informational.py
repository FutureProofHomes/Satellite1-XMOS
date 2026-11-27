"""Layer 3: Informational metrics. Reported but never gates."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import STIMULI_DIR, run_pipeline, read_wav_float
from metrics import (
    rms_db,
    snr_db,
    aec_residual_db,
    ns_snr_improvement_db,
    spectral_flatness,
    clipping_ratio,
    peak_to_rms_ratio,
    pesq_score,
)


def compute_metric(name, out_data, in_data, stim_name):
    """Dispatch metric computation by name."""
    if name == "rms":
        return rms_db(out_data[:, 0])
    elif name == "snr":
        ref = in_data[:, 2]
        if ref is not None and len(ref) > 0 and max(abs(ref.tolist())[:100]) > 0:
            return snr_db(out_data[:, 0], ref[:len(out_data)])
        return rms_db(out_data[:, 0])
    elif name == "aec_residual":
        ref = in_data[:, 2]
        return aec_residual_db(out_data[:, 0], ref, skip_frames=20)
    elif name == "snr_improvement":
        ref_speech = in_data[:, 0]
        return ns_snr_improvement_db(in_data[:, 0], out_data[:, 0], ref_speech)
    elif name == "spectral_flatness":
        return spectral_flatness(out_data[:, 0])
    elif name == "clipping":
        return clipping_ratio(out_data[:, 0])
    elif name == "crest_factor":
        return peak_to_rms_ratio(out_data[:, 0])
    elif name == "pesq":
        score = pesq_score(in_data[:, 0][:len(out_data)], out_data[:, 0])
        return score if score is not None else float("nan")
    else:
        return float("nan")


class TestDSPInformational:
    """Report metrics for tracking (never fails)."""

    def test_informational_metrics(self, pipeline_binary, output_dir, record_property):
        test_cases = [
            ("speech_clean.wav", ["rms", "spectral_flatness", "crest_factor"]),
            ("speech_echo.wav", ["aec_residual", "rms"]),
            ("speech_babble.wav", ["snr_improvement", "spectral_flatness"]),
            ("speech_quiet.wav", ["rms"]),
            ("speech_loud.wav", ["clipping", "rms"]),
            ("silence.wav", ["rms"]),
        ]

        for stim_name, metrics in test_cases:
            stim_path = STIMULI_DIR / stim_name
            if not stim_path.exists():
                continue

            out_path = output_dir / f"{Path(stim_name).stem}_out.wav"
            run_pipeline(pipeline_binary, stim_path, out_path)
            out_data, _ = read_wav_float(out_path)
            in_data, _ = read_wav_float(stim_path)

            for m in metrics:
                value = compute_metric(m, out_data, in_data, stim_name)
                if not isinstance(value, float) or value != value:  # NaN check
                    continue
                record_property(f"{stim_name}:{m}", round(value, 2))
                print(f"  {stim_name} {m}: {value:.2f}")
