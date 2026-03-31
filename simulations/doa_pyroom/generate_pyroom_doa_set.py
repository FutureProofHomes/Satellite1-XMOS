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
# Fixed lane mapping for mic position indices [N, E, S, W].
# Lane 0 is reserved for sync, so mics start from lane 1.
FIXED_MIC_LANE_MAP = [1, 2, 3, 4]
# Lane 5 (right, phase 2) carries expected angle metadata as doa_mrad.
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
    # Compass convention: North=0 deg and clockwise positive.
    # Convert to math angle first (East=0 deg and counter-clockwise positive).
    theta_math_rad = math.radians(90.0 - angle_deg)
    ux = math.cos(theta_math_rad)
    uy = math.sin(theta_math_rad)

    r = ARRAY_RADIUS_M
    fs_over_c = PIPELINE_RATE_HZ / SPEED_OF_SOUND_M_S

    a1x = r
    a1y = -r
    a2x = 0.0
    a2y = -2.0 * r
    a3x = -r
    a3y = -r

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


def simulate_mics_pyroom(
    angle_deg: float,
    segment_s: float,
    fs: int,
    seed: int,
    source_distance_m: float,
    noise_std: float,
    fmax_hz: float,
    source_type: str,
    tone_hz: float,
    multitone_hz: list[float],
) -> "list[list[float]]":
    try:
        import numpy as np
        import pyroomacoustics as pra
    except Exception as exc:
        raise RuntimeError(
            "This script requires numpy and pyroomacoustics. "
            "Install with: python3 -m pip install numpy pyroomacoustics"
        ) from exc

    room_dim = [6.0, 6.0, 2.6]
    room = pra.ShoeBox(room_dim, fs=fs, max_order=0, absorption=0.05)

    center = np.array([3.0, 3.0, 1.2])
    # Enumerate microphones clockwise starting at North: N, E, S, W.
    mic_xyz = np.array(
        [
            [0.0, ARRAY_RADIUS_M, 0.0, -ARRAY_RADIUS_M],
            [ARRAY_RADIUS_M, 0.0, -ARRAY_RADIUS_M, 0.0],
            [0.0, 0.0, 0.0, 0.0],
        ]
    )
    room.add_microphone_array(pra.MicrophoneArray(center[:, None] + mic_xyz, fs))

    # Convention: angle_deg is compass-style DoA (North=0, clockwise positive)
    # and denotes wave arrival direction. Pyroom source azimuth is the bearing
    # from array center to source, i.e. opposite of arrival direction.
    # Convert compass->math and apply +180 deg in compass space.
    dist = source_distance_m
    source_compass_deg = angle_deg + 180.0
    az = math.radians(90.0 - source_compass_deg)
    src = center + np.array([dist * math.cos(az), dist * math.sin(az), 0.0])
    src[0] = min(max(src[0], 0.5), room_dim[0] - 0.5)
    src[1] = min(max(src[1], 0.5), room_dim[1] - 0.5)

    n = int(segment_s * fs)
    t = np.arange(n, dtype=np.float32) / float(fs)
    rng = np.random.default_rng(seed)
    if source_type == "noise":
        sig = rng.standard_normal(n).astype(np.float32)
    elif source_type == "sine":
        sig = np.sin(2.0 * np.pi * float(tone_hz) * t).astype(np.float32)
    elif source_type == "multitone":
        sig = np.zeros(n, dtype=np.float32)
        for f in multitone_hz:
            sig += np.sin(2.0 * np.pi * float(f) * t).astype(np.float32)
        sig /= max(float(len(multitone_hz)), 1.0)
    else:
        f0 = 300.0
        f1 = fmax_hz
        if f1 <= f0:
            raise ValueError(f"fmax_hz must be > {f0}")
        k = (f1 - f0) / max(segment_s, 1e-6)
        phase = 2.0 * np.pi * (f0 * t + 0.5 * k * t * t)
        sig = np.sin(phase).astype(np.float32)

    if noise_std > 0.0 and source_type != "noise":
        sig += noise_std * rng.standard_normal(n).astype(np.float32)

    fade = int(0.03 * fs)
    if fade > 0 and (2 * fade) < n:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        sig[:fade] *= ramp
        sig[-fade:] *= ramp[::-1]

    room.add_source(src, signal=sig)
    room.simulate()
    mic_array = room.mic_array
    if mic_array is None:
        raise RuntimeError("pyroomacoustics did not create a microphone array")
    out = mic_array.signals[:, :n]
    return [out[i, :].tolist() for i in range(4)]


def simulate_mics_lag_synth(
    angle_deg: float,
    segment_s: float,
    fs: int,
) -> "list[list[float]]":
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
        if lane == 0:
            raise ValueError("mic_input_channel_map cannot include sync lane 0")
        channel = lane // 3
        phase = lane % 3
        if channel not in (0, 1):
            raise ValueError(f"Invalid lane channel from map value {lane}")
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
        description="Generate pyroomacoustics DoA testset, optionally inject to device"
    )
    parser.add_argument("--host", default="", help="SSH host (e.g. rasp0core2)")
    parser.add_argument(
        "--angles-deg",
        default="30,90,150,-90",
        help=(
            "Comma-separated target DoA angles per segment in firmware convention "
            "(arrival direction)"
        ),
    )
    parser.add_argument(
        "--segment-s",
        type=float,
        default=3.0,
        help="Seconds per angle segment",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=123,
        help="Noise generation seed",
    )
    parser.add_argument(
        "--source-distance-m",
        type=float,
        default=2.0,
        help="Source distance from array center in meters (pyroom mode)",
    )
    parser.add_argument(
        "--noise-std",
        type=float,
        default=0.05,
        help="Additive white-noise std for source signal in pyroom mode",
    )
    parser.add_argument(
        "--fmax-hz",
        type=float,
        default=3200.0,
        help="Upper chirp frequency in Hz for pyroom mode (default: 3200)",
    )
    parser.add_argument(
        "--source-type",
        choices=["chirp", "noise", "sine", "multitone"],
        default="chirp",
        help="Pyroom source signal type (default: chirp)",
    )
    parser.add_argument(
        "--tone-hz",
        type=float,
        default=1000.0,
        help="Tone frequency for --source-type sine",
    )
    parser.add_argument(
        "--multitone-hz",
        default="400,800,1200,1600",
        help="Comma-separated frequencies for --source-type multitone",
    )
    parser.add_argument(
        "--out-wav",
        default=None,
        help="Local output WAV path (default: temp file)",
    )
    parser.add_argument(
        "--out-expected",
        default=None,
        help="Local expected-schedule JSON path (default: alongside wav)",
    )
    parser.add_argument(
        "--remote-wav",
        default="/tmp/doa_pyroom_set.wav",
        help="Remote WAV target path",
    )
    parser.add_argument(
        "--aplay-dev",
        default="hw:0,0",
        help="Remote aplay device",
    )
    parser.add_argument(
        "--inject-and-play",
        action="store_true",
        help="Copy WAV to host and start blocking playback via aplay",
    )
    parser.add_argument(
        "--out-lag-fixture",
        default=None,
        help=(
            "Optional CSV fixture for doa_from_lags_test with lines "
            "angle_deg,lag10,lag20,lag30"
        ),
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Only generate lag fixture CSV; skip pyroom synthesis and WAV output",
    )
    parser.add_argument(
        "--signal-model",
        choices=["pyroom", "lag-synth"],
        default="pyroom",
        help="Mic signal synthesis model (default: pyroom)",
    )
    args = parser.parse_args()

    angles = parse_angles(args.angles_deg)
    multitone_hz = parse_angles(args.multitone_hz)

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
        if args.signal_model == "lag-synth":
            mics_f = simulate_mics_lag_synth(angle, args.segment_s, PIPELINE_RATE_HZ)
        else:
            mics_f = simulate_mics_pyroom(
                angle,
                args.segment_s,
                PIPELINE_RATE_HZ,
                args.seed + idx,
                args.source_distance_m,
                args.noise_std,
                args.fmax_hz,
                args.source_type,
                args.tone_hz,
                multitone_hz,
            )
        peak = max(max(abs(v) for v in ch) for ch in mics_f)
        if peak < 1e-9:
            scale = 1.0
        else:
            scale = 0.7 * ((2**31 - 1) / peak)
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

    if args.out_wav:
        out_wav = Path(args.out_wav)
    else:
        out_wav = Path(tempfile.gettempdir()) / "doa_pyroom_set.wav"
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    write_stereo_wav_s32(out_wav, all_left, all_right)

    if args.out_expected:
        out_expected = Path(args.out_expected)
    else:
        out_expected = out_wav.with_suffix(".expected.json")
    out_expected.write_text(json.dumps(schedule, indent=2) + "\n")

    print(f"WAV: {out_wav}")
    print(f"Expected schedule: {out_expected}")
    print(f"Fixed mic lane map [N,E,S,W]: {FIXED_MIC_LANE_MAP}")
    print(f"Expected angle metadata lane: {EXPECTED_ANGLE_LANE} (doa_mrad)")
    print("Angle convention: firmware DoA (arrival direction)")
    if args.signal_model == "pyroom":
        print(
            "Pyroom parameters: "
            f"source_distance_m={args.source_distance_m}, "
            f"noise_std={args.noise_std}, "
            f"fmax_hz={args.fmax_hz}, "
            f"source_type={args.source_type}, "
            f"tone_hz={args.tone_hz}, "
            f"multitone_hz={','.join(str(v) for v in multitone_hz)}"
        )

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
        play_cmd = (
            f"aplay -D {args.aplay_dev} -f S32_LE -r {I2S_RATE_HZ} -c 2 "
            f"{shlex.quote(args.remote_wav)}"
        )
        print(f"Playing on host {args.host}: {play_cmd}")
        res = run_ssh(
            args.host, play_cmd, timeout=int(len(angles) * args.segment_s) + 60
        )
        if res.returncode != 0:
            raise RuntimeError(f"aplay failed:\n{res.stdout}\n{res.stderr}")

    if args.host:
        print("\nPlot command:")
        print(
            "python3 tools/doa/plot_live_doa_over_ssh.py "
            f"--host {args.host} --source stream --poll-s 0.1 --expected-file {shlex.quote(str(out_expected))}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
