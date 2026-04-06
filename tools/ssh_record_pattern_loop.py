#!/usr/bin/env python3

import argparse
import asyncio
import os
import sys
import tempfile
import time
import wave
from pathlib import Path

from hil_utils import RemoteAudioSession, SSHSession
from typing import cast


async def _ensure_dir(sess: SSHSession, path: str) -> None:
    await sess.run(["/bin/sh", "-lc", f"mkdir -p {path}"])


def _decode_pcm_32(raw: bytes) -> list[int]:
    out = []
    for i in range(0, len(raw), 4):
        val = int.from_bytes(raw[i : i + 4], "little", signed=True)
        out.append(val)
    return out


def _dump_samples(wav_path: Path, *, count: int = 12) -> None:
    with wave.open(str(wav_path), "rb") as wf:
        num_channels = wf.getnchannels()
        rate_hz = wf.getframerate()
        sample_width = wf.getsampwidth()
        num_frames = wf.getnframes()
        raw = wf.readframes(min(num_frames, count))

    if num_channels != 2 or sample_width != 4:
        print(f"dump: unsupported format channels={num_channels} width={sample_width}")
        return

    samples = _decode_pcm_32(raw)
    left = samples[0::2]
    right = samples[1::2]
    print(f"dump: rate_hz={rate_hz} frames={num_frames}")
    print(
        "dump: left="
        + ", ".join(
            f"0x{(v & 0xFFFFFFFF):08x}(hi={((v >> 24) & 0xFF):02x})" for v in left
        )
    )
    print(
        "dump: right="
        + ", ".join(
            f"0x{(v & 0xFFFFFFFF):08x}(hi={((v >> 24) & 0xFF):02x})" for v in right
        )
    )


def _check_channel_pattern(
    samples: list[int], expected_hi: int
) -> tuple[bool, float, float]:
    if len(samples) < 6:
        return False, 0.0, 0.0

    while samples and ((samples[0] >> 24) & 0xFF) != expected_hi:
        samples = samples[1:]
    if len(samples) < 6:
        return False, 0.0, 0.0

    best_triplet = 0.0
    best_hi = 0.0
    for offset in range(3):
        total_triplets = (len(samples) - offset) // 3
        if total_triplets == 0:
            continue

        ok_triplets = 0
        match_hi = 0
        total_samples = total_triplets * 3
        for idx in range(total_triplets):
            base_idx = offset + idx * 3
            triplet = samples[base_idx : base_idx + 3]
            his = [((v >> 24) & 0xFF) for v in triplet]
            match_hi += sum(1 for h in his if h == expected_hi)

            lows = [(v & 0x003FFFFF) for v in triplet]
            if lows[0] == lows[1] == lows[2]:
                ok_triplets += 1

        hi_ratio = match_hi / total_samples
        triplet_ratio = ok_triplets / total_triplets
        if triplet_ratio > best_triplet:
            best_triplet = triplet_ratio
            best_hi = hi_ratio

    ok = best_hi >= 0.90 and best_triplet >= 0.90
    return ok, best_hi, best_triplet


def _check_pattern_unpacked(
    wav_path: Path,
    *,
    expected_left_hi: int,
    expected_right_hi: int,
) -> tuple[bool, str]:
    with wave.open(str(wav_path), "rb") as wf:
        num_channels = wf.getnchannels()
        rate_hz = wf.getframerate()
        sample_width = wf.getsampwidth()
        num_frames = wf.getnframes()
        if num_channels != 2:
            return False, f"bad_channels={num_channels}"
        if rate_hz != 48000:
            return False, f"bad_rate={rate_hz}"
        if sample_width != 4:
            return False, f"bad_width={sample_width}"
        raw = wf.readframes(num_frames)

    samples = _decode_pcm_32(raw)
    left = samples[0::2]
    right = samples[1::2]

    left_ok, left_hi, left_diff = _check_channel_pattern(left, expected_left_hi)
    right_ok, right_hi, right_diff = _check_channel_pattern(right, expected_right_hi)
    ok = left_ok and right_ok
    msg = (
        f"left_hi={left_hi:.3f} left_trip={left_diff:.3f} "
        f"right_hi={right_hi:.3f} right_trip={right_diff:.3f}"
    )
    return ok, msg


def _check_packed_channel(
    samples: list[int], expected_mic_his: tuple[int, int]
) -> tuple[bool, float, float]:
    if len(samples) < 3:
        return False, 0.0, 0.0

    total_triplets = len(samples) // 3
    if total_triplets == 0:
        return False, 0.0, 0.0

    ok_triplets = 0
    low_match = 0
    for idx in range(total_triplets):
        triplet = samples[idx * 3 : idx * 3 + 3]
        his = [((v >> 24) & 0xFF) for v in triplet]
        if all(h in his for h in expected_mic_his):
            ok_triplets += 1
            lows = [
                (v & 0x00FFFFFF)
                for v in triplet
                if ((v >> 24) & 0xFF) in expected_mic_his
            ]
            if len(lows) == 2 and lows[0] == lows[1]:
                low_match += 1

    triplet_ratio = ok_triplets / total_triplets
    low_ratio = low_match / max(1, ok_triplets)
    ok = triplet_ratio >= 0.90 and low_ratio >= 0.90
    return ok, triplet_ratio, low_ratio


def _check_pattern_packed(wav_path: Path) -> tuple[bool, str]:
    with wave.open(str(wav_path), "rb") as wf:
        num_channels = wf.getnchannels()
        rate_hz = wf.getframerate()
        sample_width = wf.getsampwidth()
        num_frames = wf.getnframes()
        if num_channels != 2:
            return False, f"bad_channels={num_channels}"
        if rate_hz != 48000:
            return False, f"bad_rate={rate_hz}"
        if sample_width != 4:
            return False, f"bad_width={sample_width}"
        raw = wf.readframes(num_frames)

    samples = _decode_pcm_32(raw)
    left = samples[0::2]
    right = samples[1::2]

    left_ok, left_trip, left_low = _check_packed_channel(left, (1, 3))
    right_ok, right_trip, right_low = _check_packed_channel(right, (2, 4))
    ok = left_ok and right_ok
    msg = (
        f"left_trip={left_trip:.3f} left_low={left_low:.3f} "
        f"right_trip={right_trip:.3f} right_low={right_low:.3f}"
    )
    return ok, msg


def _check_mic_output_channel(
    samples: list[int], expected_hi: int
) -> tuple[bool, float, float]:
    if len(samples) < 3:
        return False, 0.0, 0.0

    total = len(samples)
    match_hi = 0
    phase_counts = [0, 0, 0]
    for val in samples:
        if ((val >> 24) & 0xFF) != expected_hi:
            continue
        match_hi += 1
        phase = (val >> 22) & 0x03
        if phase < 3:
            phase_counts[phase] += 1

    hi_ratio = match_hi / total
    phase_total = sum(phase_counts)
    phase_ratio = 0.0
    if phase_total > 0:
        phase_ratio = min(phase_counts) / phase_total

    ok = hi_ratio >= 0.90 and phase_ratio >= 0.15
    return ok, hi_ratio, phase_ratio


def _check_pattern_mic_output(wav_path: Path) -> tuple[bool, str]:
    with wave.open(str(wav_path), "rb") as wf:
        num_channels = wf.getnchannels()
        rate_hz = wf.getframerate()
        sample_width = wf.getsampwidth()
        num_frames = wf.getnframes()
        if num_channels != 2:
            return False, f"bad_channels={num_channels}"
        if rate_hz != 48000:
            return False, f"bad_rate={rate_hz}"
        if sample_width != 4:
            return False, f"bad_width={sample_width}"
        raw = wf.readframes(num_frames)

    samples = _decode_pcm_32(raw)
    left = samples[0::2]
    right = samples[1::2]

    left_ok, left_trip, left_phase = _check_mic_output_channel(left, 1)
    right_ok, right_trip, right_phase = _check_mic_output_channel(right, 2)
    ok = left_ok and right_ok
    msg = (
        f"left_hi={left_trip:.3f} left_phase={left_phase:.3f} "
        f"right_hi={right_trip:.3f} right_phase={right_phase:.3f}"
    )
    return ok, msg


async def _run(args: argparse.Namespace) -> int:
    if not args.host:
        print("error: --host or SAT1_RPI_HOST is required", file=sys.stderr)
        return 2

    expected_hi = args.mic_index + 1
    sess = await SSHSession.connect(args.host)
    rec_sess = cast(RemoteAudioSession, await RemoteAudioSession.connect(args.host))
    try:
        if args.reset_before:
            reset_out = await sess.run(
                [args.sat1_cmd, "xmos", "reset"], timeout=20, check=False
            )
            if reset_out.exit_status != 0:
                stdout = reset_out.stdout.strip() if reset_out.stdout else "(no stdout)"
                stderr = reset_out.stderr.strip() if reset_out.stderr else "(no stderr)"
                print(
                    "error: xmos reset failed: "
                    f"rc={reset_out.exit_status} stdout={stdout} stderr={stderr}",
                    file=sys.stderr,
                )
                return 2
            if args.reset_wait_seconds > 0:
                await asyncio.sleep(args.reset_wait_seconds)
        await _ensure_dir(sess, args.sd_dir)
        if args.pattern_mode == "unpacked":
            pack_out = await sess.run(
                [
                    args.sat1_cmd,
                    "xmos",
                    "set-mic-pipeline-settings",
                    "--json",
                    '{"mic_output":{"pack_extra_upsample_channels":0}}',
                ],
                timeout=20,
                check=False,
            )
            if pack_out.exit_status != 0:
                stdout = pack_out.stdout.strip() if pack_out.stdout else "(no stdout)"
                stderr = pack_out.stderr.strip() if pack_out.stderr else "(no stderr)"
                print(
                    "error: set-mic-pipeline-settings failed: "
                    f"rc={pack_out.exit_status} stdout={stdout} stderr={stderr}",
                    file=sys.stderr,
                )
                return 2
        if args.mic_output_left is not None:
            target_output_left = args.mic_output_left
        else:
            target_output_left = args.mic_output_base + args.mic_index
        if args.mic_output_right is not None:
            target_output_right = args.mic_output_right
        else:
            target_output_right = target_output_left
        set_out = await sess.run(
            [
                args.sat1_cmd,
                "xmos",
                "set-mic-output",
                str(target_output_left),
                str(target_output_right),
            ],
            timeout=20,
            check=False,
        )
        if set_out.exit_status != 0:
            stdout = set_out.stdout.strip() if set_out.stdout else "(no stdout)"
            stderr = set_out.stderr.strip() if set_out.stderr else "(no stderr)"
            print(
                "error: set-mic-output failed: "
                f"rc={set_out.exit_status} stdout={stdout} stderr={stderr}",
                file=sys.stderr,
            )
            return 2

        passed = 0
        failed = 0
        with tempfile.TemporaryDirectory() as tmp_dir:
            local_dir = Path(tmp_dir)
            for idx in range(args.iterations):
                remote_rec = f"{args.sd_dir}/pattern_record_{idx:03d}.wav"
                t0 = time.monotonic()
                await rec_sess.start_record(
                    remote_path=remote_rec,
                    num_channels=2,
                    rate_hz=args.rate,
                    fmt=args.format,
                    arecord_args=[
                        f"-D{args.arecord_device}",
                        f"-d{args.record_seconds}",
                    ],
                )
                status = await rec_sess.wait()
                elapsed = time.monotonic() - t0

                local_rec = local_dir / f"pattern_record_{idx:03d}.wav"
                await sess.sftp_get(remote_rec, local_rec, preserve=True)

                if args.pattern_mode == "packed":
                    ok, msg = _check_pattern_packed(local_rec)
                elif args.pattern_mode == "mic-output":
                    ok, msg = _check_pattern_mic_output(local_rec)
                else:
                    left_hi = args.expected_left_hi
                    right_hi = args.expected_right_hi
                    if left_hi is None:
                        left_hi = expected_hi
                    if right_hi is None:
                        right_hi = expected_hi
                    ok, msg = _check_pattern_unpacked(
                        local_rec,
                        expected_left_hi=left_hi,
                        expected_right_hi=right_hi,
                    )
                if ok:
                    passed += 1
                    outcome = "PASS"
                else:
                    failed += 1
                    outcome = "FAIL"
                print(
                    f"[{idx + 1:03d}/{args.iterations}] {outcome} "
                    f"arecord={status} {elapsed:.2f}s {msg}"
                )
                if not ok:
                    fail_path = Path.cwd() / "pattern_fail.wav"
                    local_rec.replace(fail_path)
                    print(f"saved failure wav: {fail_path}")
                    _dump_samples(fail_path)
                    print("stopping on first failure")
                    break

        print(f"summary: passed={passed} failed={failed} expected_hi={expected_hi}")
        return 0 if failed == 0 else 1
    finally:
        await sess.close()
        await rec_sess.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a recording loop and validate the mic pattern"
    )
    parser.add_argument(
        "--host",
        default=os.getenv("SAT1_RPI_HOST", ""),
        help="SAT1 RPi SSH host (default: SAT1_RPI_HOST env)",
    )
    parser.add_argument(
        "--sat1-cmd",
        default=os.getenv("SAT1_RPI_CLI_CMD", "sat1"),
        help="SAT1 CLI command on remote host (default: SAT1_RPI_CLI_CMD or 'sat1')",
    )
    parser.add_argument(
        "--sd-dir",
        default=os.getenv("SAT1_RPI_SD_DIR", "/home/pi/.cache/sat1_wav_bench"),
        help="Remote SD-backed dir (default: /home/pi/.cache/sat1_wav_bench)",
    )
    parser.add_argument(
        "--arecord-device",
        default=os.getenv("SAT1_HIL_ARECORD_DEV", "hw:0,1"),
        help="ALSA device for arecord (default: SAT1_HIL_ARECORD_DEV or hw:0,1)",
    )
    parser.add_argument(
        "--record-seconds",
        type=int,
        default=3,
        help="Record duration in seconds (default: 3)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=100,
        help="Number of iterations (default: 100)",
    )
    parser.add_argument(
        "--rate",
        type=int,
        default=48000,
        help="Sample rate for recording (default: 48000)",
    )
    parser.add_argument(
        "--format",
        default="S32_LE",
        help="Sample format for recording (default: S32_LE)",
    )
    parser.add_argument(
        "--mic-index",
        type=int,
        default=0,
        help="Mic index to route (default: 0 -> expected_hi=1)",
    )
    parser.add_argument(
        "--mic-output-base",
        type=int,
        default=4,
        help="Mic output base channel (default: 4)",
    )
    parser.add_argument(
        "--mic-output-left",
        type=int,
        default=None,
        help="Explicit left output channel (default: base+mic-index)",
    )
    parser.add_argument(
        "--mic-output-right",
        type=int,
        default=None,
        help="Explicit right output channel (default: left)",
    )
    parser.add_argument(
        "--expected-left-hi",
        type=int,
        default=None,
        help="Expected left hi-byte for unpacked mode (default: mic-index+1)",
    )
    parser.add_argument(
        "--expected-right-hi",
        type=int,
        default=None,
        help="Expected right hi-byte for unpacked mode (default: expected-left-hi)",
    )
    parser.add_argument(
        "--pattern-mode",
        choices=("packed", "unpacked", "mic-output"),
        default="packed",
        help="Pattern check mode (default: packed)",
    )
    parser.add_argument(
        "--reset-before",
        action="store_true",
        help="Reset XMOS before running the loop",
    )
    parser.add_argument(
        "--reset-wait-seconds",
        type=float,
        default=2.0,
        help="Seconds to wait after reset (default: 2.0)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
