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
ARRAY_RADIUS_M = 0.0355


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


def get_remote_mic_map(host: str, py_cmd: str) -> list[int]:
    script = (
        "import json;"
        "from satellite1.sat1_hat import XMOS;"
        "x=XMOS();x.setup();"
        "s=x.get_mic_input_settings();"
        "print(json.dumps([int(v) for v in s.mic_input_channel_map]));"
        "c=getattr(x,'_cntrl',None);"
        "c.close() if c is not None and hasattr(c,'close') else None"
    )
    remote_cmd = " ".join(shlex.quote(v) for v in shlex.split(py_cmd) + ["-c", script])
    res = run_ssh(host, remote_cmd, timeout=40)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to read mic map: {res.stdout}\n{res.stderr}")
    lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("No mic map output from remote host")
    return [int(v) for v in json.loads(lines[-1])]


def simulate_mics_pyroom(
    angle_deg: float,
    segment_s: float,
    fs: int,
    seed: int,
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
    mic_xyz = np.array(
        [
            [ARRAY_RADIUS_M, 0.0, -ARRAY_RADIUS_M, 0.0],
            [0.0, ARRAY_RADIUS_M, 0.0, -ARRAY_RADIUS_M],
            [0.0, 0.0, 0.0, 0.0],
        ]
    )
    room.add_microphone_array(pra.MicrophoneArray(center[:, None] + mic_xyz, fs))

    # Convention: angle_deg follows current firmware DoA output convention.
    # Firmware reports the wave arrival direction. Pyroom source azimuth is the
    # direction from array center to source, which is the opposite vector.
    # Therefore place the synthetic source at angle + 180 deg.
    dist = 2.0
    az = math.radians(angle_deg + 180.0)
    src = center + np.array([dist * math.cos(az), dist * math.sin(az), 0.0])
    src[0] = min(max(src[0], 0.5), room_dim[0] - 0.5)
    src[1] = min(max(src[1], 0.5), room_dim[1] - 0.5)

    n = int(segment_s * fs)
    t = np.arange(n, dtype=np.float32) / float(fs)
    f0 = 300.0
    f1 = 3200.0
    k = (f1 - f0) / max(segment_s, 1e-6)
    phase = 2.0 * np.pi * (f0 * t + 0.5 * k * t * t)
    sig = np.sin(phase).astype(np.float32)

    rng = np.random.default_rng(seed)
    sig += 0.05 * rng.standard_normal(n).astype(np.float32)

    fade = int(0.03 * fs)
    if fade > 0 and (2 * fade) < n:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        sig[:fade] *= ramp
        sig[-fade:] *= ramp[::-1]

    room.add_source(src, signal=sig)
    room.simulate()
    out = room.mic_array.signals[:, :n]
    return [out[i, :].tolist() for i in range(4)]


def pack_mics_to_stereo_48k(
    mic_frames_16k: list[list[int]],
    mic_input_channel_map: list[int],
) -> tuple[list[int], list[int]]:
    frame_count_16k = len(mic_frames_16k[0])
    frame_count_48k = frame_count_16k * UPSAMPLE_FACTOR
    left = [0 for _ in range(frame_count_48k)]
    right = [0 for _ in range(frame_count_48k)]

    for mic_idx, lane in enumerate(mic_input_channel_map):
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
    parser.add_argument("--host", required=True, help="SSH host (e.g. rasp0core2)")
    parser.add_argument(
        "--py-cmd",
        default="/opt/satellite1/venv/bin/python",
        help="Remote python command used to read mic map",
    )
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
        "--mic-map",
        default="4,5,0,1",
        help="Mic input map override (default: 4,5,0,1). Use 'auto' to query device",
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
    args = parser.parse_args()

    angles = parse_angles(args.angles_deg)
    if args.mic_map and args.mic_map != "auto":
        mic_map = [int(v) for v in args.mic_map.split(",") if v.strip()]
    else:
        mic_map = get_remote_mic_map(args.host, args.py_cmd)

    if len(mic_map) != 4:
        raise RuntimeError(f"Need 4-entry mic map, got: {mic_map}")

    schedule: list[dict] = []
    all_left: list[int] = []
    all_right: list[int] = []

    for idx, angle in enumerate(angles):
        mics_f = simulate_mics_pyroom(
            angle, args.segment_s, PIPELINE_RATE_HZ, args.seed + idx
        )
        peak = max(max(abs(v) for v in ch) for ch in mics_f)
        if peak < 1e-9:
            scale = 1.0
        else:
            scale = 0.7 * ((2**31 - 1) / peak)
        mics_i = [
            [int(max(min(v * scale, 2**31 - 1), -(2**31))) for v in ch] for ch in mics_f
        ]
        left, right = pack_mics_to_stereo_48k(mics_i, mic_map)
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
    print(f"Mic map used: {mic_map}")
    print("Angle convention: firmware DoA (arrival direction)")

    if args.inject_and_play:
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

    print("\nPlot command:")
    print(
        "python3 tools/e2e/plot_doa_over_ssh.py "
        f"--host {args.host} --source stream --poll-s 0.1 --expected-file {shlex.quote(str(out_expected))}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
