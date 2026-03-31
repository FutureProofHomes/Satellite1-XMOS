#!/usr/bin/env python3

import argparse
import json
import math
import shlex
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path


I2S_RATE_HZ = 48000
PIPELINE_RATE_HZ = 16000
UPSAMPLE_FACTOR = I2S_RATE_HZ // PIPELINE_RATE_HZ
PACKAGED_SYNC_WORD = 0x7E57A55A
ARRAY_RADIUS_M = 0.0355
SPEED_OF_SOUND_M_S = 343.0
FIXED_MIC_LANE_MAP = [1, 2, 3, 4]  # [N,E,S,W]
EXPECTED_ANGLE_LANE = 5


def parse_angles(text: str) -> list[float]:
    out: list[float] = []
    for tok in text.split(","):
        tok = tok.strip()
        if tok:
            out.append(float(tok))
    if not out:
        raise ValueError("No angles provided")
    return out


def run_ssh(host: str, cmd: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, cmd],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def synthesize_lags_from_angle(angle_deg: float) -> tuple[int, int, int]:
    theta_math_rad = math.radians(90.0 - angle_deg)
    ux = math.cos(theta_math_rad)
    uy = math.sin(theta_math_rad)

    r = ARRAY_RADIUS_M
    fs_over_c = PIPELINE_RATE_HZ / SPEED_OF_SOUND_M_S

    a1x, a1y = r, -r
    a2x, a2y = 0.0, -2.0 * r
    a3x, a3y = -r, -r

    lag10 = int(round(fs_over_c * ((a1x * ux) + (a1y * uy))))
    lag20 = int(round(fs_over_c * ((a2x * ux) + (a2y * uy))))
    lag30 = int(round(fs_over_c * ((a3x * ux) + (a3y * uy))))
    return lag10, lag20, lag30


def write_lag_fixture(path: Path, angles: list[float]) -> None:
    lines = ["# angle_deg,lag10,lag20,lag30"]
    for angle in angles:
        lag10, lag20, lag30 = synthesize_lags_from_angle(angle)
        lines.append(f"{angle:.6f},{lag10},{lag20},{lag30}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def angle_deg_to_doa_mrad(angle_deg: float) -> int:
    return int(round(math.radians(angle_deg) * 1000.0))


def simulate_mics_lag_synth(
    angle_deg: float, segment_s: float, fs: int
) -> list[list[float]]:
    if fs != PIPELINE_RATE_HZ:
        raise ValueError("lag-synth mode currently requires 16 kHz")

    lag10, lag20, lag30 = synthesize_lags_from_angle(angle_deg)
    n = int(segment_s * fs)
    base_n = [0.0 for _ in range(n)]

    pulse_amp = 1.0
    pulse_offset = 80
    step = 240
    for frame_start in range(0, n, step):
        idx = frame_start + pulse_offset
        if idx < n:
            base_n[idx] = pulse_amp

    def shifted(src: list[float], lag: int) -> list[float]:
        out = [0.0 for _ in range(n)]
        for i in range(n):
            j = i - lag
            if 0 <= j < n:
                out[i] = src[j]
        return out

    n_ch = base_n
    e_ch = shifted(base_n, lag10)
    s_ch = shifted(base_n, lag20)
    w_ch = shifted(base_n, lag30)
    return [n_ch, e_ch, s_ch, w_ch]


def pack_mics_to_stereo_48k(
    mic_frames_16k: list[list[int]],
    expected_doa_mrad_16k: list[int] | None = None,
) -> tuple[list[int], list[int]]:
    frame_count_16k = len(mic_frames_16k[0])
    frame_count_48k = frame_count_16k * UPSAMPLE_FACTOR
    left = [0 for _ in range(frame_count_48k)]
    right = [0 for _ in range(frame_count_48k)]

    for i in range(frame_count_16k):
        left[i * UPSAMPLE_FACTOR] = PACKAGED_SYNC_WORD

    if expected_doa_mrad_16k is not None:
        if len(expected_doa_mrad_16k) != frame_count_16k:
            raise ValueError("expected_doa_mrad_16k length must match 16k frame count")
        channel = EXPECTED_ANGLE_LANE // 3
        phase = EXPECTED_ANGLE_LANE % 3
        for i in range(frame_count_16k):
            out_idx = (i * UPSAMPLE_FACTOR) + phase
            if channel == 0:
                left[out_idx] = expected_doa_mrad_16k[i]
            else:
                right[out_idx] = expected_doa_mrad_16k[i]

    for mic_idx, lane in enumerate(FIXED_MIC_LANE_MAP):
        channel = lane // 3
        phase = lane % 3
        for i in range(frame_count_16k):
            out_idx = (i * UPSAMPLE_FACTOR) + phase
            if channel == 0:
                left[out_idx] = mic_frames_16k[mic_idx][i]
            else:
                right[out_idx] = mic_frames_16k[mic_idx][i]
    return left, right


def write_stereo_wav_s32(path: Path, left: list[int], right: list[int]) -> None:
    if len(left) != len(right):
        raise ValueError("Left/right channel lengths do not match")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(4)
        wf.setframerate(I2S_RATE_HZ)
        data = bytearray()
        for l, r in zip(left, right):
            data.extend(struct.pack("<ii", l, r))
        wf.writeframes(data)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate deterministic DoA lag-synth test set, optionally inject to device"
    )
    parser.add_argument("--host", default="", help="SSH host (e.g. rasp0core2)")
    parser.add_argument("--angles-deg", default="30,90,150,-90")
    parser.add_argument("--segment-s", type=float, default=3.0)
    parser.add_argument("--out-wav", default=None)
    parser.add_argument("--out-expected", default=None)
    parser.add_argument("--remote-wav", default="/tmp/doa_fixture_set.wav")
    parser.add_argument("--aplay-dev", default="hw:0,0")
    parser.add_argument("--inject-and-play", action="store_true")
    parser.add_argument("--out-lag-fixture", default=None)
    parser.add_argument("--fixture-only", action="store_true")
    args = parser.parse_args()

    angles = parse_angles(args.angles_deg)

    if args.fixture_only and not args.out_lag_fixture:
        raise RuntimeError("--fixture-only requires --out-lag-fixture")

    if args.out_lag_fixture:
        out_fixture = Path(args.out_lag_fixture)
        write_lag_fixture(out_fixture, angles)
        print(f"Lag fixture: {out_fixture}")

    if args.fixture_only:
        return 0

    schedule: list[dict] = []
    all_left: list[int] = []
    all_right: list[int] = []

    for idx, angle in enumerate(angles):
        mics_f = simulate_mics_lag_synth(angle, args.segment_s, PIPELINE_RATE_HZ)
        peak = max(max(abs(v) for v in ch) for ch in mics_f)
        scale = 1.0 if peak < 1e-9 else 0.7 * ((2**31 - 1) / peak)
        mics_i = [
            [int(max(min(v * scale, 2**31 - 1), -(2**31))) for v in ch] for ch in mics_f
        ]
        expected_doa_mrad = angle_deg_to_doa_mrad(angle)
        expected_doa_mrad_16k = [expected_doa_mrad for _ in range(len(mics_i[0]))]
        left, right = pack_mics_to_stereo_48k(mics_i, expected_doa_mrad_16k)
        all_left.extend(left)
        all_right.extend(right)
        schedule.append(
            {
                "start_s": idx * args.segment_s,
                "end_s": (idx + 1) * args.segment_s,
                "angle_deg": angle,
            }
        )

    out_wav = (
        Path(args.out_wav)
        if args.out_wav
        else Path(tempfile.gettempdir()) / "doa_fixture_set.wav"
    )
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    write_stereo_wav_s32(out_wav, all_left, all_right)

    out_expected = (
        Path(args.out_expected)
        if args.out_expected
        else out_wav.with_suffix(".expected.json")
    )
    out_expected.write_text(json.dumps(schedule, indent=2) + "\n")

    print(f"WAV: {out_wav}")
    print(f"Expected schedule: {out_expected}")
    print(f"Fixed mic lane map [N,E,S,W]: {FIXED_MIC_LANE_MAP}")
    print(f"Expected angle metadata lane: {EXPECTED_ANGLE_LANE} (doa_mrad)")

    if args.inject_and_play:
        if not args.host:
            raise RuntimeError("--inject-and-play requires --host")
        scp = subprocess.run(
            ["scp", str(out_wav), f"{args.host}:{args.remote_wav}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if scp.returncode != 0:
            raise RuntimeError(f"scp failed:\n{scp.stdout}\n{scp.stderr}")
        play_cmd = f"aplay -D {args.aplay_dev} -f S32_LE -r {I2S_RATE_HZ} -c 2 {shlex.quote(args.remote_wav)}"
        print(f"Playing on host {args.host}: {play_cmd}")
        res = run_ssh(
            args.host, play_cmd, timeout=int(len(angles) * args.segment_s) + 60
        )
        if res.returncode != 0:
            raise RuntimeError(f"aplay failed:\n{res.stdout}\n{res.stderr}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
