#!/usr/bin/env python3
"""
Generate deterministic WAV fixture for mic-gain HIL tests.

Produces a packaged-input format WAV file with:
- Sync word (0x7E57A55A) in lane 0, phase 0 of every 48kHz triplet
- Sine wave in lanes 1-4 (N,E,S,W simulated mics)
- Optional expected DoA angle metadata in lane 5

The sine wave has stable RMS for gain-change verification.
"""

import argparse
import math
import struct
import sys
from pathlib import Path


# Constants matching firmware expectations
I2S_RATE_HZ = 48000
PIPELINE_RATE_HZ = 16000
UPSAMPLE_FACTOR = I2S_RATE_HZ // PIPELINE_RATE_HZ  # = 3
PACKAGED_SYNC_WORD = 0x7E57A55A

# Lane mapping (matches firmware)
SYNC_LANE = 0
MIC_LANES = [1, 2, 3, 4]  # N, E, S, W
EXPECTED_ANGLE_LANE = 5
TOTAL_LANES = 6


def generate_sine_wave(
    duration_s: float,
    frequency_hz: float = 1000.0,
    amplitude: float = 0.3,
) -> list[float]:
    """
    Generate a sine wave at 16kHz pipeline rate.

    Args:
        duration_s: Duration in seconds
        frequency_hz: Sine frequency in Hz (at 16kHz)
        amplitude: Amplitude (0.0 to 1.0, will be scaled to int32 range)

    Returns:
        List of float samples at 16kHz rate
    """
    n_samples = int(duration_s * PIPELINE_RATE_HZ)
    omega = 2.0 * math.pi * frequency_hz / PIPELINE_RATE_HZ
    return [amplitude * math.sin(omega * i) for i in range(n_samples)]


def apply_inter_mic_delays(
    base_signal: list[float],
    angle_deg: float = 0.0,
) -> list[list[float]]:
    """
    Apply angle-dependent delays to simulate 4-mic array.

    For mic-gain tests, we use angle=0 (front) which means
    all mics receive the same signal with minimal delay differences.
    This maximizes signal coherence across channels.

    Args:
        base_signal: Reference signal (North mic)
        angle_deg: Angle of arrival in degrees (0 = front/North)

    Returns:
        List of 4 delayed signals [N, E, S, W]
    """
    # For simplicity in mic-gain tests, use zero delay for all mics
    # This ensures maximum signal coherence and simplifies verification
    return [base_signal.copy() for _ in range(4)]


def pack_to_stereo_48k(
    mic_signals_16k: list[list[float]],
    expected_angle_mrad: int = 0,
) -> tuple[list[int], list[int]]:
    """
    Pack 16kHz mic signals into stereo 48kHz packaged format.

    Format per 48kHz triplet (samples 3i, 3i+1, 3i+2):
    - Left channel: lanes 0, 1, 2
    - Right channel: lanes 3, 4, 5

    Lane assignments:
    - Lane 0: Sync word (every triplet)
    - Lanes 1-4: Mic signals (N, E, S, W)
    - Lane 5: Expected angle metadata (optional)

    Args:
        mic_signals_16k: List of 4 signals at 16kHz [N, E, S, W]
        expected_angle_mrad: Expected DoA angle in milliradians

    Returns:
        Tuple of (left_channel, right_channel) as lists of int32 samples
    """
    n_frames_16k = len(mic_signals_16k[0])
    n_samples_48k = n_frames_16k * UPSAMPLE_FACTOR

    left = [0] * n_samples_48k
    right = [0] * n_samples_48k

    # Scale factor to convert float amplitude to int32 range
    # Leave headroom to avoid clipping after gain application
    scale = int(0.5 * (2**31 - 1))  # ~50% of max int32

    for i in range(n_frames_16k):
        base_idx = i * UPSAMPLE_FACTOR

        # Lane 0: Sync word (left channel, phase 0)
        left[base_idx + 0] = PACKAGED_SYNC_WORD

        # Lanes 1-2: Mic N (lane 1), Mic E (lane 2) on left channel
        left[base_idx + 1] = int(mic_signals_16k[0][i] * scale)  # N
        left[base_idx + 2] = int(mic_signals_16k[1][i] * scale)  # E

        # Lanes 3-5: Mic S (lane 3), Mic W (lane 4), Angle (lane 5) on right channel
        right[base_idx + 0] = int(mic_signals_16k[2][i] * scale)  # S
        right[base_idx + 1] = int(mic_signals_16k[3][i] * scale)  # W
        right[base_idx + 2] = expected_angle_mrad  # Angle metadata

    return left, right


def write_stereo_wav_s32(
    path: Path,
    left: list[int],
    right: list[int],
) -> None:
    """
    Write stereo S32LE WAV file.

    Args:
        path: Output file path
        left: Left channel samples (int32)
        right: Right channel samples (int32)
    """
    import wave

    if len(left) != len(right):
        raise ValueError(
            f"Channel length mismatch: left={len(left)}, right={len(right)}"
        )

    path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(4)  # 32-bit
        wf.setframerate(I2S_RATE_HZ)

        # Interleave samples
        data = bytearray()
        for l, r in zip(left, right):
            data.extend(struct.pack("<ii", l, r))

        wf.writeframes(data)

    duration_s = len(left) / I2S_RATE_HZ
    print(f"Written: {path}")
    print(f"  Duration: {duration_s:.3f}s")
    print(f"  Samples per channel: {len(left)}")
    print(f"  File size: {path.stat().st_size:,} bytes")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate deterministic WAV fixture for mic-gain HIL tests"
    )
    parser.add_argument(
        "--duration-s",
        type=float,
        default=5.0,
        help="Duration in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="tests/test_hil/fixtures/mic_gain_test_fixture.wav",
        help=(
            "Output WAV path "
            "(default: tests/test_hil/fixtures/mic_gain_test_fixture.wav)"
        ),
    )
    parser.add_argument(
        "--amplitude",
        type=float,
        default=0.3,
        help="Amplitude 0-1 (default: 0.3, ~50%% of int32 max)",
    )
    parser.add_argument(
        "--sine-frequency-hz",
        type=float,
        default=1000.0,
        help="Sine frequency in Hz (default: 1000)",
    )

    args = parser.parse_args()

    output_path = Path(args.output)

    # Generate base sine wave at 16kHz
    print("Generating sine wave...")
    print(f"  Duration: {args.duration_s}s")
    print(f"  Amplitude: {args.amplitude}")
    print(f"  Frequency: {args.sine_frequency_hz} Hz")

    base_signal = generate_sine_wave(
        duration_s=args.duration_s,
        frequency_hz=args.sine_frequency_hz,
        amplitude=args.amplitude,
    )

    # Apply (zero) inter-mic delays for coherent signal
    mic_signals = apply_inter_mic_delays(base_signal, angle_deg=0.0)

    # Pack to stereo 48kHz
    left, right = pack_to_stereo_48k(mic_signals, expected_angle_mrad=0)

    # Write WAV file
    write_stereo_wav_s32(output_path, left, right)

    # Verify sync word placement
    sync_count = sum(1 for s in left[::3] if s == PACKAGED_SYNC_WORD)
    expected_sync_count = len(left) // 3
    print(f"  Sync words: {sync_count}/{expected_sync_count} (lane 0, phase 0)")

    if sync_count != expected_sync_count:
        print("ERROR: Sync word count mismatch!", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
