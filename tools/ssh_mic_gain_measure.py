#!/usr/bin/env python3

import argparse
import asyncio
import os
import sys
import tempfile
import time
import wave
import ast
import re
from typing import cast
from pathlib import Path

from hil_utils import RemoteAudioSession, SSHSession


def _log(quiet: bool, message: str) -> None:
    if not quiet:
        print(message)


async def _ensure_dir(sess: SSHSession, path: str) -> None:
    await sess.run(["/bin/sh", "-lc", f"mkdir -p {path}"])


async def _copy_and_time(
    sess: SSHSession,
    local: Path,
    remote_dir: str,
    quiet: bool,
) -> float:
    await _ensure_dir(sess, remote_dir)
    remote_path = f"{remote_dir}/{local.name}"
    t0 = time.monotonic()
    await sess.sftp_put(local, remote_path, preserve=True)
    elapsed = time.monotonic() - t0
    _log(quiet, f"elapsed: {elapsed:.3f}s -> {remote_path}")
    return elapsed


async def _run(
    host: str,
    wav_path: Path,
    sd_dir: str,
    *,
    num_channels: int,
    rate_hz: int,
    fmt: str,
    aplay_device: str,
    arecord_device: str,
    record_seconds: int,
    sat1_cmd: str,
    analyze: bool,
    injected_mode: str,
    analyze_only: bool,
    analyze_lane: int,
    analyze_channel: int,
    window_ms: int,
    hop_ms: int,
    mic_index: int,
    mic_output_base: int,
    mic_gain: float,
    recording_mode: str,
    gain_sweep: bool,
    gain_values: list[float],
    gain_waits: list[float],
    snapshot: bool,
    snapshot_delay: float,
    snapshot_count: int,
    snapshot_period: float,
    run_dir: Path | None,
    quiet: bool,
) -> int:
    if not wav_path.exists():
        print(f"error: wav file not found: {wav_path}", file=sys.stderr)
        return 2

    if analyze:
        _log(quiet, "analysis: injected")
        _analyze_wav(
            wav_path,
            mode=injected_mode,
            lane=analyze_lane,
            channel=analyze_channel,
            window_ms=window_ms,
            hop_ms=hop_ms,
            quiet=quiet,
        )
        if analyze_only:
            return 0

    sess = await SSHSession.connect(host)
    play_sess = cast(RemoteAudioSession, await RemoteAudioSession.connect(host))
    rec_sess = cast(RemoteAudioSession, await RemoteAudioSession.connect(host))
    try:
        if gain_sweep:
            await _run_gain_sweep(sess, sat1_cmd, gain_values, gain_waits)
            return 0
        t0 = time.monotonic()
        await _copy_and_time(sess, wav_path, sd_dir, quiet)
        _log(quiet, f"timing.copy: {time.monotonic() - t0:.3f}s")
        remote_wav = f"{sd_dir}/{wav_path.name}"
        remote_rec = f"{sd_dir}/recorded_{wav_path.stem}.wav"

        if recording_mode == "unpacked":
            t0 = time.monotonic()
            pack_out = await sess.run(
                [
                    sat1_cmd,
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
            _log(
                quiet,
                f"timing.set_pipeline_settings: {time.monotonic() - t0:.3f}s",
            )

        target_output_ch = mic_output_base + mic_index
        t0 = time.monotonic()
        await sess.run(
            [
                sat1_cmd,
                "xmos",
                "set-mic-output",
                str(target_output_ch),
                str(target_output_ch),
            ],
            timeout=20,
        )
        _log(quiet, f"timing.set_output_channel: {time.monotonic() - t0:.3f}s")

        t0 = time.monotonic()
        mic_gain_q30 = int(round(mic_gain * (1 << 30)))
        await sess.run(
            [
                sat1_cmd,
                "xmos",
                "set-mic-input-gains",
                "--mic-gain",
                str(mic_gain_q30),
            ],
            timeout=20,
        )
        _log(
            quiet,
            f"timing.set_mic_gain: {time.monotonic() - t0:.3f}s "
            f"(gain={mic_gain:.3f}, q30={mic_gain_q30})",
        )

        settings = await sess.run(
            [sat1_cmd, "xmos", "get-mic-input-settings"],
            timeout=20,
            check=False,
        )
        if settings.stdout:
            _log(quiet, f"mic_input_settings: {settings.stdout.strip()}")

        output_settings = await sess.run(
            [sat1_cmd, "xmos", "get-mic-output-settings"],
            timeout=20,
            check=False,
        )
        if output_settings.stdout:
            _log(quiet, f"mic_output_settings: {output_settings.stdout.strip()}")

        t0 = time.monotonic()
        cmd = [
            sat1_cmd,
            "xmos",
            "set-mic-input-routing",
            "--ref-source-mode",
            "0",
            "--mic-source-mode",
            "1",
            "--mic-input-channel-map",
            "1",
            "2",
            "3",
            "4",
        ]
        await sess.run(cmd, timeout=20)
        _log(quiet, f"timing.set_input_routing: {time.monotonic() - t0:.3f}s")

        t0 = time.monotonic()
        await rec_sess.start_record(
            remote_path=remote_rec,
            num_channels=num_channels,
            rate_hz=rate_hz,
            fmt=fmt,
            arecord_args=[f"-D{arecord_device}", f"-d{record_seconds}"],
        )
        _log(quiet, f"timing.start_record: {time.monotonic() - t0:.3f}s")

        t0 = time.monotonic()
        await play_sess.start_play(
            remote_path=remote_wav,
            num_channels=num_channels,
            aplay_args=[f"-D{aplay_device}"],
        )
        _log(quiet, f"timing.start_play: {time.monotonic() - t0:.3f}s")

        if snapshot:
            await asyncio.sleep(snapshot_delay)
            for idx in range(snapshot_count):
                snap = await sess.run(
                    [sat1_cmd, "xmos", "get-mic-input-packaged-snapshot"],
                    timeout=20,
                    check=False,
                )
                _print_snapshot(
                    idx,
                    _coerce_text(snap.stdout),
                    _coerce_text(snap.stderr),
                )
                if idx + 1 < snapshot_count:
                    await asyncio.sleep(snapshot_period)

        t0 = time.monotonic()
        play_status, rec_status = await asyncio.gather(
            play_sess.wait(), rec_sess.wait()
        )
        _log(quiet, f"timing.wait: {time.monotonic() - t0:.3f}s")

        _log(quiet, f"aplay exit: {play_status}")
        _log(quiet, f"arecord exit: {rec_status}")
        _log(quiet, f"recorded: {remote_rec}")

        info = await sess.run(
            ["/bin/sh", "-lc", f"ls -l {remote_rec}"],
            check=False,
        )
        if info.stdout:
            info_text = _coerce_text(info.stdout)
            if info_text:
                _log(quiet, info_text.strip())

        if analyze:
            tmp_ctx = None
            if run_dir is None:
                tmp_ctx = tempfile.TemporaryDirectory(prefix="sat1_hil_run_")
                local_root = Path(tmp_ctx.name)
            else:
                local_root = run_dir
                local_root.mkdir(parents=True, exist_ok=True)

            try:
                local_rec = local_root / f"{wav_path.stem}_recorded.wav"
                t0 = time.monotonic()
                await sess.sftp_get(remote_rec, local_rec, preserve=True)
                _log(quiet, f"timing.download: {time.monotonic() - t0:.3f}s")
                _log(quiet, f"recorded_local: {local_rec}")
                _log(quiet, "analysis: recorded")
                _analyze_wav(
                    local_rec,
                    mode=recording_mode,
                    lane=analyze_lane,
                    channel=analyze_channel,
                    window_ms=window_ms,
                    hop_ms=hop_ms,
                    quiet=quiet,
                )
                _estimate_gain(
                    injected_path=wav_path,
                    recorded_path=local_rec,
                    recording_mode=recording_mode,
                    injected_mode=injected_mode,
                    channel=analyze_channel,
                    window_ms=window_ms,
                    hop_ms=hop_ms,
                    quiet=quiet,
                )
            finally:
                if tmp_ctx is not None:
                    tmp_ctx.cleanup()
    finally:
        await sess.close()
        await play_sess.close()
        await rec_sess.close()

    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Upload a WAV, play/record over SSH, and estimate mic gain.")
    )
    parser.add_argument(
        "--host",
        default=os.getenv("SAT1_RPI_HOST", ""),
        help="SAT1 RPi SSH host (default: SAT1_RPI_HOST env)",
    )
    parser.add_argument(
        "--wav",
        help="Local path to WAV file to upload",
    )
    parser.add_argument(
        "--sd-dir",
        default=os.getenv("SAT1_RPI_SD_DIR", "/home/pi/.cache/sat1_wav_bench"),
        help="Remote SD-backed dir (default: /home/pi/.cache/sat1_wav_bench)",
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=2,
        help="Channel count for play/record (default: 2)",
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
        "--aplay-device",
        default=os.getenv("SAT1_HIL_APLAY_DEV", "hw:0,0"),
        help="ALSA device for aplay (default: SAT1_HIL_APLAY_DEV or hw:0,0)",
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
        default=10,
        help="Number of runs to execute (default: 10)",
    )
    parser.add_argument(
        "--loop-gains",
        nargs="+",
        type=float,
        default=None,
        help="Mic gains to cycle per iteration (overrides --iterations)",
    )
    parser.add_argument(
        "--sat1-cmd",
        default=os.getenv("SAT1_RPI_CLI_CMD", "sat1"),
        help="SAT1 CLI command on remote host (default: SAT1_RPI_CLI_CMD or 'sat1')",
    )
    parser.add_argument(
        "--run-dir",
        default=os.getenv("SAT1_HIL_RUN_DIR", ""),
        help=(
            "Local directory for downloaded recording artifacts during analysis "
            "(default: temporary run dir)"
        ),
    )
    parser.add_argument(
        "--mic-index",
        type=int,
        default=0,
        help="Mic index to route (default: 0)",
    )
    parser.add_argument(
        "--mic-output-base",
        type=int,
        default=4,
        help="Mic output base channel (default: 4)",
    )
    parser.add_argument(
        "--mic-gain",
        type=float,
        default=1.0,
        help="Mic gain (float, default: 1.0)",
    )
    parser.add_argument(
        "--recording-mode",
        choices=("unpacked", "packed"),
        default="unpacked",
        help="Mic output mode for recording (default: unpacked)",
    )
    parser.add_argument(
        "--gain-sweep",
        action="store_true",
        help="Sweep mic gain values and read back settings",
    )
    parser.add_argument(
        "--gain-values",
        nargs="+",
        type=float,
        default=[0.25, 0.5, 0.75, 1.0],
        help="Mic gains to sweep (default: 0.25 0.5 0.75 1.0)",
    )
    parser.add_argument(
        "--gain-waits",
        nargs="+",
        type=float,
        default=[0.0, 0.05, 0.1, 0.25, 0.5],
        help="Seconds to wait before readback (default: 0 0.05 0.1 0.25 0.5)",
    )
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="Capture mic input packaged snapshot during play/record",
    )
    parser.add_argument(
        "--snapshot-delay",
        type=float,
        default=0.2,
        help="Delay before snapshot in seconds (default: 0.2)",
    )
    parser.add_argument(
        "--snapshot-count",
        type=int,
        default=1,
        help="Number of snapshots to capture (default: 1)",
    )
    parser.add_argument(
        "--snapshot-period",
        type=float,
        default=0.2,
        help="Seconds between snapshots (default: 0.2)",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Analyze the injected WAV locally before upload",
    )
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="Stop after local injected WAV analysis",
    )
    parser.add_argument(
        "--injected-mode",
        choices=("packed", "raw"),
        default="raw",
        help="Mode for injected WAV analysis (default: raw)",
    )
    parser.add_argument(
        "--analyze-lane",
        type=int,
        default=1,
        help="Lane index for packed analysis (default: 1; valid: 1-4)",
    )
    parser.add_argument(
        "--analyze-channel",
        type=int,
        default=0,
        help="Channel index for raw/unpacked analysis (default: 0)",
    )
    parser.add_argument(
        "--window-ms",
        type=int,
        default=100,
        help="RMS window size at 16 kHz in ms (default: 100)",
    )
    parser.add_argument(
        "--hop-ms",
        type=int,
        default=50,
        help="RMS hop size at 16 kHz in ms (default: 50)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.analyze_only:
        args.analyze = True
    if not args.host and not args.analyze_only:
        print("error: --host or SAT1_RPI_HOST is required", file=sys.stderr)
        return 2
    if not args.gain_sweep and not args.wav:
        print("error: --wav is required unless --gain-sweep is set", file=sys.stderr)
        return 2
    wav_path = Path(args.wav).expanduser().resolve() if args.wav else Path(".")
    if args.loop_gains:
        gains = args.loop_gains
        iterations = len(gains)
    else:
        gains = [args.mic_gain] * max(1, args.iterations)
        iterations = len(gains)
    quiet = iterations > 1
    last_rc = 0
    for idx in range(iterations):
        mic_gain = gains[idx]
        run_dir = Path(args.run_dir).expanduser().resolve() if args.run_dir else None
        rc = asyncio.run(
            _run(
                args.host,
                wav_path,
                args.sd_dir,
                num_channels=args.channels,
                rate_hz=args.rate,
                fmt=args.format,
                aplay_device=args.aplay_device,
                arecord_device=args.arecord_device,
                record_seconds=args.record_seconds,
                sat1_cmd=args.sat1_cmd,
                analyze=args.analyze,
                injected_mode=args.injected_mode,
                analyze_only=args.analyze_only,
                analyze_lane=args.analyze_lane,
                analyze_channel=args.analyze_channel,
                window_ms=args.window_ms,
                hop_ms=args.hop_ms,
                mic_index=args.mic_index,
                mic_output_base=args.mic_output_base,
                mic_gain=mic_gain,
                recording_mode=args.recording_mode,
                gain_sweep=args.gain_sweep,
                gain_values=args.gain_values,
                gain_waits=args.gain_waits,
                snapshot=args.snapshot,
                snapshot_delay=args.snapshot_delay,
                snapshot_count=args.snapshot_count,
                snapshot_period=args.snapshot_period,
                run_dir=run_dir,
                quiet=quiet,
            )
        )
        last_rc = rc
        if iterations > 1:
            outcome = "PASS" if rc == 0 else "FAIL"
            print(f"[{idx + 1:02d}/{iterations}] {outcome} gain={mic_gain:.3f}")
            if rc != 0:
                break
    return last_rc


def _analyze_wav(
    wav_path: Path,
    *,
    mode: str,
    lane: int,
    channel: int,
    window_ms: int,
    hop_ms: int,
    quiet: bool,
) -> None:
    with wave.open(str(wav_path), "rb") as wf:
        num_channels = wf.getnchannels()
        rate_hz = wf.getframerate()
        sample_width = wf.getsampwidth()
        num_frames = wf.getnframes()

        if mode == "packed":
            if num_channels != 2:
                raise ValueError(f"expected stereo WAV, got {num_channels} channels")
            if lane < 1 or lane > 4:
                raise ValueError("lane must be in range 1-4")
            if rate_hz != 48000:
                raise ValueError(f"expected 48kHz packaged WAV, got {rate_hz}")

        raw = wf.readframes(num_frames)
    samples = _decode_pcm(raw, sample_width, num_channels)

    if mode == "packed":
        left = samples[0::2]
        right = samples[1::2]
        if lane in (1, 2):
            phase = lane
            signal = left[phase::3]
        else:
            phase = lane - 3
            signal = right[phase::3]
        analysis_rate = 16000
        detail = f"  lane: {lane}"
    else:
        if channel < 0 or channel >= num_channels:
            raise ValueError(f"channel must be in range 0-{num_channels - 1}")
        signal = samples[channel::num_channels]
        analysis_rate = rate_hz
        detail = f"  channel: {channel}"

    stats = _rms_window_stats(signal, analysis_rate, window_ms, hop_ms)
    if not stats:
        _log(quiet, "analysis: no RMS windows computed")
        return

    _log(quiet, "analysis:")
    _log(quiet, f"  rate_hz: {rate_hz}")
    _log(quiet, f"  channels: {num_channels}")
    _log(quiet, f"  sample_width_bytes: {sample_width}")
    _log(quiet, f"  mode: {mode}")
    _log(quiet, f"  analysis_rate: {analysis_rate}")
    _log(quiet, detail)
    _log(quiet, f"  window_ms: {window_ms}")
    _log(quiet, f"  hop_ms: {hop_ms}")
    _log(quiet, f"  rms_min: {stats['rms_min']:.3f}")
    _log(quiet, f"  rms_max: {stats['rms_max']:.3f}")
    _log(quiet, f"  rms_mean: {stats['rms_mean']:.3f}")
    _log(quiet, f"  rms_p50: {stats['rms_p50']:.3f}")
    _log(quiet, f"  rms_p5: {stats['rms_p5']:.3f}")
    _log(quiet, f"  rms_p95: {stats['rms_p95']:.3f}")
    if not quiet:
        _print_activity_segments(
            stats["rms_vals"],
            stats["window"],
            stats["hop"],
            analysis_rate,
            threshold=stats["threshold"],
        )


def _estimate_gain(
    *,
    injected_path: Path,
    recorded_path: Path,
    recording_mode: str,
    injected_mode: str,
    channel: int,
    window_ms: int,
    hop_ms: int,
    quiet: bool,
) -> None:
    injected = _load_wav_channel(injected_path, channel)
    recorded = _load_wav_channel(recorded_path, channel)

    inj_signal, inj_rate = injected
    rec_signal, rec_rate = recorded

    if injected_mode == "packed" and inj_rate == 48000:
        inj_signal = _extract_packed_lane(inj_signal, channel)
        inj_rate = 16000

    if recording_mode == "unpacked" and rec_rate == 48000 and inj_rate == 16000:
        rec_signal = rec_signal[::3]
        rec_rate = 16000

    inj_stats = _rms_window_stats(inj_signal, inj_rate, window_ms, hop_ms)
    rec_stats = _rms_window_stats(rec_signal, rec_rate, window_ms, hop_ms)
    if not inj_stats or not rec_stats:
        _log(quiet, "gain_estimate: insufficient RMS data")
        return

    denom = inj_stats["active_p50"] or inj_stats["rms_p50"]
    numer = rec_stats["active_p50"] or rec_stats["rms_p50"]
    if denom == 0:
        _log(quiet, "gain_estimate: injected RMS is zero")
        return
    ratio = numer / denom
    msg = "gain_estimate:"
    if inj_rate != rec_rate:
        msg += f" rate_mismatch(inj={inj_rate}, rec={rec_rate})"
    _log(
        quiet,
        f"{msg} ratio={ratio:.4f} inj_p50={denom:.3f} rec_p50={numer:.3f}",
    )


def _load_wav_channel(wav_path: Path, channel: int) -> tuple[list[float], int]:
    with wave.open(str(wav_path), "rb") as wf:
        num_channels = wf.getnchannels()
        rate_hz = wf.getframerate()
        sample_width = wf.getsampwidth()
        num_frames = wf.getnframes()
        if channel < 0 or channel >= num_channels:
            raise ValueError(f"channel must be in range 0-{num_channels - 1}")
        raw = wf.readframes(num_frames)

    samples = _decode_pcm(raw, sample_width, num_channels)
    return samples[channel::num_channels], rate_hz


def _extract_packed_lane(samples: list[float], channel: int) -> list[float]:
    if channel not in (0, 1):
        raise ValueError("packed mode expects channel 0 or 1")
    phase = 1 if channel == 0 else 2
    return samples[phase::3]


def _rms_window_stats(
    samples: list[float],
    rate_hz: int,
    window_ms: int,
    hop_ms: int,
) -> dict | None:
    window = max(1, int(rate_hz * (window_ms / 1000.0)))
    hop = max(1, int(rate_hz * (hop_ms / 1000.0)))
    rms_vals = []
    for start in range(0, max(0, len(samples) - window + 1), hop):
        segment = samples[start : start + window]
        if not segment:
            continue
        rms_vals.append(_rms(segment))

    if not rms_vals:
        return None

    rms_sorted = sorted(rms_vals)
    rms_mean = sum(rms_sorted) / len(rms_sorted)
    rms_p50 = rms_sorted[len(rms_sorted) // 2]
    rms_p5 = rms_sorted[int(0.05 * (len(rms_sorted) - 1))]
    rms_p95 = rms_sorted[int(0.95 * (len(rms_sorted) - 1))]
    rms_max = rms_sorted[-1]
    rms_min = rms_sorted[0]
    threshold = max(rms_max * 0.2, 1.0)
    active_vals = [v for v in rms_vals if v >= threshold]
    active_p50 = rms_p50
    if active_vals:
        active_sorted = sorted(active_vals)
        active_p50 = active_sorted[len(active_sorted) // 2]

    return {
        "rms_vals": rms_vals,
        "rms_mean": rms_mean,
        "rms_p50": rms_p50,
        "rms_p5": rms_p5,
        "rms_p95": rms_p95,
        "rms_max": rms_max,
        "rms_min": rms_min,
        "active_p50": active_p50,
        "threshold": threshold,
        "window": window,
        "hop": hop,
    }


def _decode_pcm(raw: bytes, sample_width: int, num_channels: int) -> list[float]:
    if sample_width == 2:
        return _decode_pcm_16(raw)
    if sample_width == 3:
        return _decode_pcm_24(raw)
    if sample_width == 4:
        return _decode_pcm_32(raw)
    raise ValueError(f"unsupported sample width: {sample_width}")


def _decode_pcm_16(raw: bytes) -> list[float]:
    out = []
    for i in range(0, len(raw), 2):
        val = int.from_bytes(raw[i : i + 2], "little", signed=True)
        out.append(float(val))
    return out


def _decode_pcm_24(raw: bytes) -> list[float]:
    out = []
    for i in range(0, len(raw), 3):
        b0 = raw[i]
        b1 = raw[i + 1]
        b2 = raw[i + 2]
        val = b0 | (b1 << 8) | (b2 << 16)
        if val & 0x800000:
            val -= 1 << 24
        out.append(float(val))
    return out


def _decode_pcm_32(raw: bytes) -> list[float]:
    out = []
    for i in range(0, len(raw), 4):
        val = int.from_bytes(raw[i : i + 4], "little", signed=True)
        out.append(float(val))
    return out


def _rms(samples: list[float]) -> float:
    if not samples:
        return 0.0
    acc = 0.0
    for s in samples:
        acc += s * s
    return (acc / len(samples)) ** 0.5


def _print_snapshot(index: int, stdout: str | None, stderr: str | None) -> None:
    prefix = f"snapshot[{index}]"
    if stdout:
        parsed = _parse_snapshot_repr(stdout.strip())
        if parsed is None:
            print(f"{prefix}: {stdout.strip()}")
        else:
            _print_snapshot_summary(prefix, parsed)
    else:
        print(f"{prefix}: (no stdout)")
    if stderr:
        print(f"{prefix} stderr: {stderr.strip()}")


def _coerce_text(value: str | bytes | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _parse_snapshot_repr(text: str) -> dict | None:
    if "MicInputPackagedSnapshot" not in text:
        return None
    try:
        frame_counter = _extract_int(text, "frame_counter")
        sample_count = _extract_int(text, "sample_count")
        mic_map = _extract_tuple(text, "mic_input_channel_map")
        packaged = _extract_nested_tuple(text, "packaged_lane_samples")
        mapped = _extract_nested_tuple(text, "mapped_mic_samples")
    except ValueError:
        return None

    return {
        "frame_counter": frame_counter,
        "sample_count": sample_count,
        "mic_input_channel_map": mic_map,
        "packaged_lane_samples": packaged,
        "mapped_mic_samples": mapped,
    }


def _extract_int(text: str, key: str) -> int:
    match = re.search(rf"{key}=(-?\d+)", text)
    if not match:
        raise ValueError(key)
    return int(match.group(1))


def _extract_tuple(text: str, key: str) -> tuple:
    match = re.search(rf"{key}=(\([^\)]*\))", text)
    if not match:
        raise ValueError(key)
    return ast.literal_eval(match.group(1))


def _extract_nested_tuple(text: str, key: str) -> tuple:
    match = re.search(rf"{key}=(\(\(.*?\)\))", text)
    if not match:
        raise ValueError(key)
    return ast.literal_eval(match.group(1))


def _print_snapshot_summary(prefix: str, snap: dict) -> None:
    print(
        f"{prefix}: frame={snap['frame_counter']} samples={snap['sample_count']} "
        f"map={snap['mic_input_channel_map']}"
    )

    packaged = snap["packaged_lane_samples"]
    mapped = snap["mapped_mic_samples"]
    print(f"{prefix}: packaged_lane_rms={_rms_rows(packaged)}")
    print(f"{prefix}: mapped_mic_rms={_rms_rows(mapped)}")


def _rms_rows(rows: tuple) -> tuple:
    out = []
    for row in rows:
        values = [float(v) for v in row]
        out.append(round(_rms(values), 3))
    return tuple(out)


def _print_activity_segments(
    rms_vals: list[float],
    window: int,
    hop: int,
    rate_hz: int,
    threshold: float,
) -> None:
    active = [i for i, v in enumerate(rms_vals) if v >= threshold]
    if not active:
        print("  activity: no active windows")
        return

    first = active[0]
    last = active[-1]
    pre_windows = first
    active_windows = last - first + 1
    post_windows = max(0, len(rms_vals) - last - 1)

    win_s = window / rate_hz
    hop_s = hop / rate_hz
    pre_s = pre_windows * hop_s
    active_s = (active_windows - 1) * hop_s + win_s
    post_s = post_windows * hop_s

    active_vals = rms_vals[first : last + 1]
    active_mean = sum(active_vals) / len(active_vals)
    active_sorted = sorted(active_vals)
    active_p50 = active_sorted[len(active_sorted) // 2]

    print("  activity:")
    print(f"    threshold: {threshold:.3f}")
    print(f"    pre_s: {pre_s:.3f}")
    print(f"    active_s: {active_s:.3f}")
    print(f"    post_s: {post_s:.3f}")
    print(f"    active_rms_mean: {active_mean:.3f}")
    print(f"    active_rms_p50: {active_p50:.3f}")


async def _run_gain_sweep(
    sess: SSHSession,
    sat1_cmd: str,
    gains: list[float],
    waits: list[float],
) -> None:
    print("gain_sweep:")
    for gain in gains:
        q30 = int(round(gain * (1 << 30)))
        t0 = time.monotonic()
        await sess.run(
            [sat1_cmd, "xmos", "set-mic-input-gains", "--mic-gain", str(q30)],
            timeout=20,
        )
        print(f"  set gain={gain:.3f} q30={q30} ({time.monotonic() - t0:.3f}s)")
        for wait_s in waits:
            await asyncio.sleep(wait_s)
            t1 = time.monotonic()
            settings = await sess.run(
                [sat1_cmd, "xmos", "get-mic-input-settings"],
                timeout=20,
                check=False,
            )
            msg = settings.stdout.strip() if settings.stdout else "(no output)"
            print(
                f"    wait={wait_s:.3f}s readback ({time.monotonic() - t1:.3f}s): {msg}"
            )


if __name__ == "__main__":
    raise SystemExit(main())
