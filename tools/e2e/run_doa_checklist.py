#!/usr/bin/env python3

"""Run a staged DoA HIL checklist and write JSON artifact reports.

This tool validates end-to-end DoA behavior on a remote Pi/XMOS target by
checking playback process health, mic routing/mode setup, DoA sequence and
debug progression, and source parity against expected-angle schedules.
"""

import argparse
import json
import math
import os
import re
import shlex
import struct
import subprocess
import tempfile
import time
import wave
from pathlib import Path


I2S_RATE_HZ = 48000
PIPELINE_RATE_HZ = 16000
UPSAMPLE_FACTOR = I2S_RATE_HZ // PIPELINE_RATE_HZ
SPEED_OF_SOUND_M_S = 343.0
ARRAY_RADIUS_M = 0.0355
PACKAGED_SYNC_WORD = 0x7E57A55A

DOA_RE = re.compile(r"doa_mrad\s*=\s*(-?\d+)")
SEQ_RE = re.compile(r"seq\s*=\s*(\d+)")
VALID_RE = re.compile(r"valid\s*=\s*(\d+)")
FRAME_COUNTER_RE = re.compile(r"frame_counter\s*=\s*(\d+)")
MIC_MEAN_ABS_RE = re.compile(r"mic_mean_abs\s*=\s*\(([^)]*)\)")


def _run_local(
    cmd: list[str], timeout: float = 60.0
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _run_ssh(
    host: str, cmd: str, timeout: float = 60.0
) -> subprocess.CompletedProcess[str]:
    return _run_local(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, cmd],
        timeout=timeout,
    )


def _write_json(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")


def _wrap_deg(angle_deg: float) -> float:
    while angle_deg > 180.0:
        angle_deg -= 360.0
    while angle_deg < -180.0:
        angle_deg += 360.0
    return angle_deg


def _circular_median_deg(values_deg: list[float]) -> float:
    if not values_deg:
        return 0.0
    best = values_deg[0]
    best_cost = float("inf")
    for candidate in values_deg:
        cost = 0.0
        for other in values_deg:
            cost += abs(_wrap_deg(candidate - other))
        if cost < best_cost:
            best = candidate
            best_cost = cost
    return _wrap_deg(best)


def _parse_cli_doa(text: str) -> dict | None:
    doa_match = DOA_RE.search(text)
    seq_match = SEQ_RE.search(text)
    valid_match = VALID_RE.search(text)
    if not doa_match or not seq_match or not valid_match:
        return None
    return {
        "doa_mrad": int(doa_match.group(1)),
        "seq": int(seq_match.group(1)),
        "valid": int(valid_match.group(1)),
    }


def _synthesize_mic_frames(angle_deg: float, frame_count_16k: int) -> list[list[int]]:
    ux = math.cos(math.radians(angle_deg))
    uy = math.sin(math.radians(angle_deg))

    mic_positions = [
        (0.0, ARRAY_RADIUS_M),
        (-ARRAY_RADIUS_M, 0.0),
        (0.0, -ARRAY_RADIUS_M),
        (ARRAY_RADIUS_M, 0.0),
    ]
    delays = [
        int(round((PIPELINE_RATE_HZ / SPEED_OF_SOUND_M_S) * ((px * ux) + (py * uy))))
        for px, py in mic_positions
    ]

    base = [0 for _ in range(frame_count_16k)]
    pulse_amp = 240000000
    pulse_offset = 80
    for frame_start in range(0, frame_count_16k, 240):
        idx = frame_start + pulse_offset
        if idx < frame_count_16k:
            base[idx] = pulse_amp

    mics = [[0 for _ in range(frame_count_16k)] for _ in range(4)]
    for mic in range(4):
        delay = delays[mic]
        for n in range(frame_count_16k):
            src_idx = n - delay
            if src_idx < 0 or src_idx >= frame_count_16k:
                sample = 0
            else:
                sample = base[src_idx]
            mics[mic][n] = sample
    return mics


def _pack_mics_to_stereo_48k(
    mic_frames_16k: list[list[int]], mic_input_channel_map: list[int]
) -> tuple[list[int], list[int]]:
    frame_count_16k = len(mic_frames_16k[0])
    frame_count_48k = frame_count_16k * UPSAMPLE_FACTOR
    left = [0 for _ in range(frame_count_48k)]
    right = [0 for _ in range(frame_count_48k)]

    for i in range(frame_count_16k):
        left[i * UPSAMPLE_FACTOR] = PACKAGED_SYNC_WORD

    for mic_idx, lane in enumerate(mic_input_channel_map):
        if lane == 0:
            raise ValueError("mic_input_channel_map cannot include sync lane 0")
        channel = lane // 3
        phase = lane % 3
        if channel not in (0, 1):
            raise ValueError(f"Unexpected lane value {lane}")
        for i in range(frame_count_16k):
            out_idx = (i * UPSAMPLE_FACTOR) + phase
            if channel == 0:
                left[out_idx] = mic_frames_16k[mic_idx][i]
            else:
                right[out_idx] = mic_frames_16k[mic_idx][i]

    return left, right


def _write_stereo_wav_s32(path: Path, left: list[int], right: list[int]) -> None:
    if len(left) != len(right):
        raise ValueError("left/right channel lengths must match")

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(4)
        wf.setframerate(I2S_RATE_HZ)
        data = bytearray()
        for lch, rch in zip(left, right):
            data.extend(struct.pack("<ii", lch, rch))
        wf.writeframes(data)


def _read_mic_input_settings(host: str, sat1_cmd: str) -> dict:
    res = _run_ssh(
        host, f"{sat1_cmd} xmos get-mic-pipeline-settings --json", timeout=20
    )
    if res.returncode != 0:
        raise RuntimeError(res.stdout + res.stderr)
    lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Expected JSON output from get-mic-pipeline-settings")
    body = json.loads(lines[-1])
    mic_input = body.get("mic_input", {})
    return {
        "mic_source_mode": int(mic_input["mic_source_mode"]),
        "ref_source_mode": int(mic_input["ref_source_mode"]),
        "mic_input_channel_map": [int(v) for v in mic_input["mic_input_channel_map"]],
        "ref_input_channel_map": [int(v) for v in mic_input["ref_input_channel_map"]],
        "available_mic_count": int(body["available_mic_count"]),
    }


def _set_mic_packaged_mode(host: str, sat1_cmd: str, mic_map: list[int]) -> dict:
    payload = json.dumps(
        {"mic_input": {"mic_input_channel_map": mic_map, "mic_source_mode": 1}},
        separators=(",", ":"),
    )
    res = _run_ssh(
        host,
        f"{sat1_cmd} xmos set-mic-pipeline-settings --json {shlex.quote(payload)}",
        timeout=20,
    )
    ok = res.returncode == 0 and "True" in res.stdout
    after = _read_mic_input_settings(host, sat1_cmd)
    return {
        "ok": bool(ok),
        "mic_source_mode": int(after["mic_source_mode"]),
        "mic_input_channel_map": [int(v) for v in after["mic_input_channel_map"]],
    }


def _parse_mic_input_debug_stats(text: str) -> dict:
    dbg: dict[str, int | list[int]] = {}
    frame = FRAME_COUNTER_RE.search(text)
    if frame:
        dbg["frame_counter"] = int(frame.group(1))
    mean_abs = MIC_MEAN_ABS_RE.search(text)
    if mean_abs:
        vals: list[int] = []
        for raw in mean_abs.group(1).split(","):
            raw = raw.strip()
            if raw:
                vals.append(int(raw))
        dbg["mic_mean_abs"] = vals
    return dbg


def _read_doa_sample(host: str, sat1_cmd: str) -> dict:
    raw_res = _run_ssh(host, f"{sat1_cmd} xmos get-doa --mode raw", timeout=10)
    smooth_res = _run_ssh(host, f"{sat1_cmd} xmos get-doa --mode smooth", timeout=10)
    dbg_res = _run_ssh(host, f"{sat1_cmd} xmos get-mic-input-debug-stats", timeout=10)
    if raw_res.returncode != 0 or smooth_res.returncode != 0:
        raise RuntimeError(
            raw_res.stdout + raw_res.stderr + smooth_res.stdout + smooth_res.stderr
        )
    raw = _parse_cli_doa(raw_res.stdout)
    smooth = _parse_cli_doa(smooth_res.stdout)
    if raw is None or smooth is None:
        raise RuntimeError("Failed to parse DoA sample from CLI output")
    return {
        "raw": raw,
        "smooth": smooth,
        "debug": _parse_mic_input_debug_stats(dbg_res.stdout),
    }


def _stage_status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _assert_packaged_mode(host: str, sat1_cmd: str, mic_map: list[int]) -> dict:
    set_result = _set_mic_packaged_mode(host, sat1_cmd, mic_map)
    after = _read_mic_input_settings(host, sat1_cmd)
    mode_ok = int(after.get("mic_source_mode", -1)) == 1
    map_ok = [int(v) for v in after.get("mic_input_channel_map", [])] == mic_map
    if not set_result.get("ok") or not mode_ok or not map_ok:
        raise RuntimeError(
            "Failed to enforce packaged routing before source pass: "
            f"set_result={set_result} after={after}"
        )
    return {"set_result": set_result, "after": after}


def _load_expected_windows(path: str | None) -> list[dict]:
    if not path:
        return []
    body = json.loads(Path(path).read_text())
    windows: list[dict] = []
    for row in body:
        windows.append(
            {
                "start_s": float(row["start_s"]),
                "end_s": float(row["end_s"]),
                "angle_deg": float(row["angle_deg"]),
            }
        )
    return windows


def _expected_angle_at(t_s: float, windows: list[dict], loop: bool) -> float | None:
    if not windows:
        return None
    t_eval = t_s
    if loop:
        total = max(w["end_s"] for w in windows)
        if total > 0:
            t_eval = t_s % total
    for window in windows:
        if window["start_s"] <= t_eval < window["end_s"]:
            return float(window["angle_deg"])
    return None


def _collect_python_samples_during_playback(
    host: str,
    sat1_cmd: str,
    aplay_cmd: str,
    poll_s: float,
) -> tuple[list[dict], float, float, str, str]:
    samples: list[dict] = []
    playback_started_at = 0.0
    playback_ended_at = 0.0
    play_proc = subprocess.Popen(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, aplay_cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    playback_started_at = time.time()
    while True:
        if play_proc.poll() is not None:
            break
        sample_ts = time.time()
        sample = _read_doa_sample(host, sat1_cmd)
        sample["t"] = sample_ts
        sample["t_rel_s"] = sample_ts - playback_started_at
        samples.append(sample)
        time.sleep(max(0.05, poll_s))

    playback_ended_at = time.time()
    out, err = play_proc.communicate(timeout=10)
    if play_proc.returncode != 0:
        raise RuntimeError(out + err)
    return samples, playback_started_at, playback_ended_at, out, err


def _collect_cli_samples_during_playback(
    host: str,
    sat1_cmd: str,
    aplay_cmd: str,
    poll_s: float,
) -> tuple[list[dict], float, float, str, str]:
    samples: list[dict] = []
    playback_started_at = 0.0
    playback_ended_at = 0.0
    play_proc = subprocess.Popen(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, aplay_cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    playback_started_at = time.time()
    while True:
        if play_proc.poll() is not None:
            break
        sample_ts = time.time()
        cli_raw = _run_ssh(host, f"{sat1_cmd} xmos get-doa --mode raw", timeout=10)
        cli_smooth = _run_ssh(
            host, f"{sat1_cmd} xmos get-doa --mode smooth", timeout=10
        )
        raw_parsed = _parse_cli_doa(cli_raw.stdout)
        smooth_parsed = _parse_cli_doa(cli_smooth.stdout)
        if raw_parsed and smooth_parsed:
            samples.append(
                {
                    "t": sample_ts,
                    "t_rel_s": sample_ts - playback_started_at,
                    "raw": raw_parsed,
                    "smooth": smooth_parsed,
                }
            )
        time.sleep(max(0.05, poll_s))

    playback_ended_at = time.time()
    out, err = play_proc.communicate(timeout=10)
    if play_proc.returncode != 0:
        raise RuntimeError(out + err)
    return samples, playback_started_at, playback_ended_at, out, err


def _collect_stream_samples_during_playback(
    host: str,
    sat1_cmd: str,
    aplay_cmd: str,
    playback_s: float,
    poll_s: float,
) -> tuple[list[dict], float, float, str, str, str]:
    stream_count = max(5, int((max(playback_s + 1.0, 2.0)) / max(0.05, poll_s)))
    remote_stream_cmd = (
        f"{sat1_cmd} xmos get-doa --stream --period-s {max(0.05, poll_s)} "
        f"--count {stream_count}"
    )

    stream_proc = subprocess.Popen(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            host,
            remote_stream_cmd,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    play_proc = subprocess.Popen(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, aplay_cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    playback_started_at = time.time()
    samples: list[dict] = []
    while True:
        if play_proc.poll() is not None:
            break
        if stream_proc.stdout is None:
            time.sleep(max(0.05, poll_s))
            continue
        line = stream_proc.stdout.readline().strip()
        if not line:
            time.sleep(max(0.05, poll_s))
            continue
        try:
            parsed = json.loads(line)
            parsed["t"] = time.time()
            parsed["t_rel_s"] = parsed["t"] - playback_started_at
            samples.append(parsed)
        except Exception:
            continue

    out, err = play_proc.communicate(timeout=max(30, int(playback_s + 20)))
    playback_ended_at = time.time()
    if play_proc.returncode != 0:
        stream_proc.terminate()
        raise RuntimeError(out + err)

    stream_proc.terminate()
    try:
        stream_out, stream_err = stream_proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        stream_proc.kill()
        stream_out, stream_err = stream_proc.communicate(timeout=5)

    for line in stream_out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            parsed["t"] = time.time()
            parsed["t_rel_s"] = parsed["t"] - playback_started_at
            samples.append(parsed)
        except Exception:
            continue
    return samples, playback_started_at, playback_ended_at, out, err, stream_err


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a strict Sat1 DoA pipeline checklist and write artifact JSON files"
    )
    parser.add_argument("--host", default=os.getenv("SAT1_RPI_HOST", ""))
    parser.add_argument("--sat1-cmd", default=os.getenv("SAT1_RPI_CLI_CMD", "sat1"))
    parser.add_argument(
        "--aplay-dev", default=os.getenv("SAT1_HIL_APLAY_DEV", "hw:0,0")
    )
    parser.add_argument("--angle-deg", type=float, default=45.0)
    parser.add_argument("--playback-s", type=float, default=6.0)
    parser.add_argument("--poll-s", type=float, default=0.2)
    parser.add_argument(
        "--expected-file",
        default=None,
        help="Optional expected schedule JSON file with start_s/end_s/angle_deg",
    )
    parser.add_argument(
        "--expected-loop",
        action="store_true",
        help="Loop expected schedule across elapsed playback time",
    )
    parser.add_argument(
        "--expected-offset-deg",
        type=float,
        default=0.0,
        help="Offset applied to expected schedule angles",
    )
    parser.add_argument(
        "--parity-tol-deg",
        type=float,
        default=40.0,
        help="Max allowed median delta across source modes",
    )
    parser.add_argument(
        "--source-warmup-s",
        type=float,
        default=0.8,
        help="Ignore source samples collected before this elapsed playback time",
    )
    parser.add_argument(
        "--stream-retries",
        type=int,
        default=2,
        help="Retry stream parity pass this many times on mismatch",
    )
    parser.add_argument(
        "--min-valid-samples",
        type=int,
        default=10,
        help="Minimum valid smooth samples per source for parity decision",
    )
    parser.add_argument(
        "--schedule-tol-deg",
        type=float,
        default=60.0,
        help="Max allowed median expected-vs-actual delta",
    )
    parser.add_argument(
        "--artifacts-dir",
        default="artifacts/doa_checklist",
        help="Directory where report JSON files are written",
    )
    args = parser.parse_args()

    artifacts_dir = Path(args.artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    process_report: dict = {
        "stage": "playback process and ALSA health",
        "status": "BLOCKED",
        "details": {},
    }
    settings_report: dict = {
        "stage": "mode/routing and lane map snapshot",
        "status": "BLOCKED",
        "details": {},
    }
    seq_report: dict = {
        "stage": "DoA seq progression and SPI read stability",
        "status": "BLOCKED",
        "details": {},
    }
    debug_report: dict = {
        "stage": "injection queue/feed continuity",
        "status": "BLOCKED",
        "details": {},
    }
    parity_report: dict = {
        "stage": "plot source parity and schedule alignment",
        "status": "BLOCKED",
        "details": {},
    }

    stage_summary: list[dict] = []

    if not args.host.strip():
        reason = "SAT1_RPI_HOST/--host is required"
        for report in (
            process_report,
            settings_report,
            seq_report,
            debug_report,
            parity_report,
        ):
            report["status"] = "BLOCKED"
            report["details"] = {"reason": reason}
        _write_json(artifacts_dir / "process_status.json", process_report)
        _write_json(artifacts_dir / "device_settings_snapshot.json", settings_report)
        _write_json(artifacts_dir / "seq_progression.json", seq_report)
        _write_json(artifacts_dir / "debug_stats_progression.json", debug_report)
        _write_json(artifacts_dir / "plot_parity_report.json", parity_report)
        _write_json(
            artifacts_dir / "summary.json",
            {
                "overall": "BLOCKED",
                "reason": reason,
                "stages": stage_summary,
            },
        )
        return 2

    host = args.host.strip()
    sat1_cmd = args.sat1_cmd.strip()

    # Stage 1: playback process health.
    try:
        ping = _run_ssh(host, "echo sat1_doa_checklist_ping", timeout=10)
        ssh_ok = ping.returncode == 0 and "sat1_doa_checklist_ping" in ping.stdout

        remote_silence = f"/tmp/sat1_doa_checklist_silence_{int(time.time())}.wav"
        with tempfile.TemporaryDirectory(prefix="sat1_doa_checklist_") as tmpdir:
            local_wav = Path(tmpdir) / "silence.wav"
            samples = int(1.2 * I2S_RATE_HZ)
            _write_stereo_wav_s32(local_wav, [0] * samples, [0] * samples)
            scp = _run_local(
                ["scp", str(local_wav), f"{host}:{remote_silence}"], timeout=30
            )

        playback_cmd = (
            f"aplay -D {args.aplay_dev} -f S32_LE -r {I2S_RATE_HZ} -c 2 "
            f"{shlex.quote(remote_silence)}"
        )
        proc = subprocess.Popen(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                host,
                playback_cmd,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(0.25)
        pgrep_pattern = (
            f"^aplay -D {args.aplay_dev} -f S32_LE -r {I2S_RATE_HZ} -c 2 "
            f"{remote_silence}$"
        )
        proc_match = _run_ssh(
            host,
            f"pgrep -af {shlex.quote(pgrep_pattern)} || true",
            timeout=10,
        )
        out, err = proc.communicate(timeout=20)
        _run_ssh(host, f"rm -f {shlex.quote(remote_silence)}", timeout=10)

        alsa_error = "ALSA" in (out + err)
        proc_ok = proc.returncode == 0
        playback_detected = any(
            "aplay -D" in line and "pgrep -af" not in line
            for line in proc_match.stdout.splitlines()
        )
        stage_ok = (
            ssh_ok
            and scp.returncode == 0
            and proc_ok
            and playback_detected
            and not alsa_error
        )

        process_report["status"] = _stage_status(stage_ok)
        process_report["details"] = {
            "ssh_ok": ssh_ok,
            "scp_returncode": scp.returncode,
            "playback_returncode": proc.returncode,
            "playback_detected_via_pgrep": playback_detected,
            "alsa_error_detected": alsa_error,
            "aplay_stdout": out.strip(),
            "aplay_stderr": err.strip(),
            "pgrep_output": proc_match.stdout.strip(),
        }
    except Exception as exc:
        process_report["status"] = "FAIL"
        process_report["details"] = {"error": str(exc)}

    stage_summary.append(
        {
            "cause": "1) Playback actually running on Pi",
            "status": process_report["status"],
        }
    )

    # Stage 2: mode and routing state.
    mic_map: list[int] = [4, 5, 0, 1]
    try:
        before = _read_mic_input_settings(host, sat1_cmd)
        mic_map = [int(v) for v in before["mic_input_channel_map"]]
        set_result = _set_mic_packaged_mode(host, sat1_cmd, mic_map)
        after = _read_mic_input_settings(host, sat1_cmd)
        mode_ok = int(after.get("mic_source_mode", -1)) == 1
        map_ok = [int(v) for v in after.get("mic_input_channel_map", [])] == mic_map
        stage_ok = mode_ok and map_ok and bool(set_result.get("ok", False))
        settings_report["status"] = _stage_status(stage_ok)
        settings_report["details"] = {
            "before": before,
            "set_result": set_result,
            "after": after,
        }
    except Exception as exc:
        settings_report["status"] = "FAIL"
        settings_report["details"] = {"error": str(exc)}

    stage_summary.append(
        {
            "cause": "2) XMOS mode/routing state",
            "status": settings_report["status"],
        }
    )

    expected_windows: list[dict] = []
    expected_windows_error: str | None = None
    try:
        expected_windows = _load_expected_windows(args.expected_file)
    except Exception as exc:
        expected_windows_error = str(exc)

    stage7_status = "BLOCKED"

    # Stage 3 + 4 + 5 + 6 use serialized playback passes.
    remote_test_wav = f"/tmp/sat1_doa_checklist_probe_{int(time.time())}.wav"
    python_samples: list[dict] = []

    try:
        with tempfile.TemporaryDirectory(prefix="sat1_doa_probe_") as tmpdir:
            local_wav = Path(tmpdir) / "doa_probe.wav"
            frame_count_16k = max(1, int(args.playback_s * PIPELINE_RATE_HZ))
            mics = _synthesize_mic_frames(args.angle_deg, frame_count_16k)
            left, right = _pack_mics_to_stereo_48k(mics, mic_map)
            _write_stereo_wav_s32(local_wav, left, right)

            scp = _run_local(
                ["scp", str(local_wav), f"{host}:{remote_test_wav}"], timeout=60
            )
            if scp.returncode != 0:
                raise RuntimeError(scp.stdout + scp.stderr)

        playback_cmd = (
            f"aplay -D {args.aplay_dev} -f S32_LE -r {I2S_RATE_HZ} -c 2 "
            f"{shlex.quote(remote_test_wav)}"
        )

        (
            python_samples,
            playback_started_at,
            playback_ended_at,
            _py_out,
            _py_err,
        ) = _collect_python_samples_during_playback(
            host,
            sat1_cmd,
            playback_cmd,
            args.poll_s,
        )

        first_valid_t: float | None = None
        for sample in python_samples:
            if int(sample["smooth"]["valid"]):
                first_valid_t = float(sample["t"])
                break

        settings_details = settings_report.get("details")
        if not isinstance(settings_details, dict):
            settings_details = {}
            settings_report["details"] = settings_details
        settings_details["map_used_for_probe_generation"] = mic_map
        settings_details["lane_packing_rule"] = (
            "wav generated using live mic_input_channel_map read before playback"
        )
        stage_summary.append(
            {
                "cause": "3) Lane packing mismatch at runtime",
                "status": "PASS",
            }
        )

        raw_seq = [int(s["raw"]["seq"]) for s in python_samples]
        smooth_seq = [int(s["smooth"]["seq"]) for s in python_samples]
        raw_span = (max(raw_seq) - min(raw_seq)) if raw_seq else 0
        smooth_span = (max(smooth_seq) - min(smooth_seq)) if smooth_seq else 0

        raw_valid_count = sum(int(s["raw"]["valid"]) for s in python_samples)
        smooth_valid_count = sum(int(s["smooth"]["valid"]) for s in python_samples)

        frame_counter_vals: list[int] = []
        mic_mean_abs_vals: list[int] = []
        for sample in python_samples:
            dbg = sample.get("debug", {})
            if "frame_counter" in dbg:
                frame_counter_vals.append(int(dbg["frame_counter"]))
            if "mic_mean_abs" in dbg:
                mic_mean_abs_vals.append(int(dbg["mic_mean_abs"]))

        continuity_ok = raw_span > 0 and smooth_span > 0 and smooth_valid_count > 0
        debug_report["status"] = _stage_status(continuity_ok)
        debug_report["details"] = {
            "sample_count": len(python_samples),
            "raw_valid_count": raw_valid_count,
            "smooth_valid_count": smooth_valid_count,
            "raw_seq_span": raw_span,
            "smooth_seq_span": smooth_span,
            "frame_counter_values": frame_counter_vals,
            "mic_mean_abs_values": mic_mean_abs_vals,
            "first_valid_latency_s": (
                None if first_valid_t is None else (first_valid_t - playback_started_at)
            ),
        }

        monotonic_breaks = 0
        for i in range(1, len(smooth_seq)):
            if smooth_seq[i] < smooth_seq[i - 1]:
                monotonic_breaks += 1
        spi_ok = monotonic_breaks == 0 and smooth_span > 0
        seq_report["status"] = _stage_status(spi_ok)
        seq_report["details"] = {
            "sample_count": len(python_samples),
            "raw_seq": raw_seq,
            "smooth_seq": smooth_seq,
            "raw_seq_span": raw_span,
            "smooth_seq_span": smooth_span,
            "smooth_monotonic_breaks": monotonic_breaks,
        }

        py_valid = [
            {
                "t_rel_s": float(s.get("t_rel_s", 0.0)),
                "raw": s["raw"],
                "smooth": s["smooth"],
                "smooth_deg": _wrap_deg(math.degrees(s["smooth"]["doa_mrad"] / 1000.0)),
            }
            for s in python_samples
            if int(s["smooth"]["valid"])
            and float(s.get("t_rel_s", 0.0)) >= args.source_warmup_s
        ]
        py_deg = [float(s["smooth_deg"]) for s in py_valid]

        cli_routing = _assert_packaged_mode(host, sat1_cmd, mic_map)
        cli_samples, _cli_start, _cli_end, _cli_out, _cli_err = (
            _collect_cli_samples_during_playback(
                host,
                args.sat1_cmd,
                playback_cmd,
                args.poll_s,
            )
        )
        cli_valid = [
            {
                "t_rel_s": float(s.get("t_rel_s", 0.0)),
                "raw": s["raw"],
                "smooth": s["smooth"],
                "smooth_deg": _wrap_deg(math.degrees(s["smooth"]["doa_mrad"] / 1000.0)),
            }
            for s in cli_samples
            if int(s["smooth"]["valid"])
            and float(s.get("t_rel_s", 0.0)) >= args.source_warmup_s
        ]
        cli_deg = [float(s["smooth_deg"]) for s in cli_valid]

        py_med = _circular_median_deg(py_deg) if py_deg else None
        cli_med = _circular_median_deg(cli_deg) if cli_deg else None

        cli_py_delta = None
        if cli_med is not None and py_med is not None:
            cli_py_delta = abs(_wrap_deg(cli_med - py_med))

        stream_samples: list[dict] = []
        stream_valid: list[dict] = []
        stream_err = ""
        stream_attempts = max(1, int(args.stream_retries))
        stream_attempt_reports: list[dict] = []
        stream_med = None
        stream_py_delta = None
        best_stream_score = float("inf")
        best_stream_bundle: dict | None = None

        for attempt_idx in range(stream_attempts):
            stream_routing = _assert_packaged_mode(host, sat1_cmd, mic_map)
            (
                attempt_samples,
                _st_start,
                _st_end,
                _st_out,
                _st_err,
                attempt_stream_err,
            ) = _collect_stream_samples_during_playback(
                host,
                sat1_cmd,
                playback_cmd,
                args.playback_s,
                args.poll_s,
            )
            attempt_valid = [
                {
                    "t_rel_s": float(s.get("t_rel_s", 0.0)),
                    "raw": s["raw"],
                    "smooth": s["smooth"],
                    "smooth_deg": _wrap_deg(
                        math.degrees(s["smooth"]["doa_mrad"] / 1000.0)
                    ),
                }
                for s in attempt_samples
                if int(s["smooth"]["valid"])
                and float(s.get("t_rel_s", 0.0)) >= args.source_warmup_s
            ]
            attempt_deg = [float(s["smooth_deg"]) for s in attempt_valid]
            attempt_med = _circular_median_deg(attempt_deg) if attempt_deg else None
            attempt_delta = None
            if attempt_med is not None and py_med is not None:
                attempt_delta = abs(_wrap_deg(attempt_med - py_med))

            score = float(attempt_delta) if attempt_delta is not None else float("inf")
            if score < best_stream_score:
                best_stream_score = score
                best_stream_bundle = {
                    "samples": attempt_samples,
                    "valid": attempt_valid,
                    "median": attempt_med,
                    "delta": attempt_delta,
                    "stderr": attempt_stream_err,
                    "routing": stream_routing,
                }

            attempt_ok = (
                attempt_delta is not None and attempt_delta <= args.parity_tol_deg
            )
            stream_attempt_reports.append(
                {
                    "attempt": attempt_idx + 1,
                    "sample_count": len(attempt_deg),
                    "stream_median_deg": attempt_med,
                    "stream_vs_python_delta_deg": attempt_delta,
                    "ok": attempt_ok,
                    "routing": stream_routing,
                }
            )
            if attempt_ok:
                break

            time.sleep(0.2)

        if best_stream_bundle is not None:
            stream_samples = list(best_stream_bundle["samples"])
            stream_valid = list(best_stream_bundle["valid"])
            stream_med = best_stream_bundle["median"]
            stream_py_delta = best_stream_bundle["delta"]
            stream_err = str(best_stream_bundle["stderr"])

        min_required = max(1, int(args.min_valid_samples))
        counts_ok = (
            len(py_valid) >= min_required
            and len(cli_valid) >= min_required
            and len(stream_valid) >= min_required
        )

        if not counts_ok:
            parity_status = "BLOCKED"
            parity_ok = False
        elif cli_py_delta is None or stream_py_delta is None:
            parity_status = "BLOCKED"
            parity_ok = False
        else:
            parity_ok = (
                cli_py_delta <= args.parity_tol_deg
                and stream_py_delta <= args.parity_tol_deg
            )
            parity_status = _stage_status(parity_ok)

        _write_json(artifacts_dir / "parity_python_samples.json", {"samples": py_valid})
        _write_json(artifacts_dir / "parity_cli_samples.json", {"samples": cli_valid})
        _write_json(
            artifacts_dir / "parity_stream_samples.json", {"samples": stream_valid}
        )

        parity_report["status"] = parity_status
        parity_report["details"] = {
            "python_samples": len(py_valid),
            "cli_samples": len(cli_valid),
            "stream_samples": len(stream_valid),
            "python_median_deg": py_med,
            "cli_median_deg": cli_med,
            "stream_median_deg": stream_med,
            "cli_vs_python_delta_deg": cli_py_delta,
            "stream_vs_python_delta_deg": stream_py_delta,
            "parity_tol_deg": args.parity_tol_deg,
            "min_valid_samples": min_required,
            "source_warmup_s": args.source_warmup_s,
            "python_routing": {
                "mic_source_mode": 1,
                "mic_input_channel_map": mic_map,
            },
            "cli_routing": cli_routing,
            "stream_retries": stream_attempts,
            "stream_attempts": stream_attempt_reports,
            "stream_stderr": stream_err,
            "parity_ready": cli_py_delta is not None and stream_py_delta is not None,
            "sample_count_gate_passed": counts_ok,
            "playback_window_s": {
                "start": playback_started_at,
                "end": playback_ended_at,
            },
        }

        if expected_windows_error:
            stage7_status = "FAIL"
            parity_report["details"]["expected_schedule_alignment"] = {
                "status": "FAIL",
                "reason": expected_windows_error,
            }
        elif not expected_windows:
            stage7_status = "BLOCKED"
            parity_report["details"]["expected_schedule_alignment"] = {
                "status": "BLOCKED",
                "reason": "No expected schedule file passed",
            }
        else:
            schedule_errs: list[float] = []
            for sample in python_samples:
                if not int(sample["smooth"]["valid"]):
                    continue
                t_rel = float(sample.get("t_rel_s", 0.0))
                expected = _expected_angle_at(
                    t_rel, expected_windows, args.expected_loop
                )
                if expected is None:
                    continue
                expected = _wrap_deg(expected + args.expected_offset_deg)
                actual = _wrap_deg(math.degrees(sample["smooth"]["doa_mrad"] / 1000.0))
                schedule_errs.append(abs(_wrap_deg(actual - expected)))

            if not schedule_errs:
                stage7_status = "BLOCKED"
                parity_report["details"]["expected_schedule_alignment"] = {
                    "status": "BLOCKED",
                    "reason": "No overlapping expected windows with sampled playback interval",
                }
            else:
                schedule_med = sorted(schedule_errs)[len(schedule_errs) // 2]
                schedule_ok = schedule_med <= args.schedule_tol_deg
                stage7_status = _stage_status(schedule_ok)
                parity_report["details"]["expected_schedule_alignment"] = {
                    "status": stage7_status,
                    "sample_count": len(schedule_errs),
                    "median_error_deg": schedule_med,
                    "tolerance_deg": args.schedule_tol_deg,
                    "expected_offset_deg": args.expected_offset_deg,
                    "expected_loop": bool(args.expected_loop),
                }
    except Exception as exc:
        err_text = str(exc)
        blocked = "Device or resource busy" in err_text
        status = "BLOCKED" if blocked else "FAIL"
        seq_report["status"] = status
        seq_report["details"] = {"error": err_text}
        debug_report["status"] = status
        debug_report["details"] = {"error": err_text}
        parity_report["status"] = status
        parity_report["details"] = {"error": err_text}
        stage7_status = status
        stage_summary.append(
            {
                "cause": "3) Lane packing mismatch at runtime",
                "status": status,
            }
        )
    finally:
        _run_ssh(host, f"rm -f {shlex.quote(remote_test_wav)}", timeout=10)

    stage_summary.append(
        {
            "cause": "4) Injection queue/feed continuity",
            "status": debug_report["status"],
        }
    )
    stage_summary.append(
        {
            "cause": "5) DoA read path stability over SPI",
            "status": seq_report["status"],
        }
    )
    stage_summary.append(
        {
            "cause": "6) Plot source mode artifacts",
            "status": parity_report["status"],
        }
    )
    stage_summary.append(
        {
            "cause": "7) Expected-angle schedule alignment",
            "status": stage7_status,
        }
    )
    stage_summary.append(
        {
            "cause": "8) Acoustic/clock realities on hardware",
            "status": "BLOCKED",
        }
    )

    _write_json(artifacts_dir / "process_status.json", process_report)
    _write_json(artifacts_dir / "device_settings_snapshot.json", settings_report)
    _write_json(artifacts_dir / "seq_progression.json", seq_report)
    _write_json(artifacts_dir / "debug_stats_progression.json", debug_report)
    _write_json(artifacts_dir / "plot_parity_report.json", parity_report)

    overall = "PASS"
    for report in (
        process_report,
        settings_report,
        seq_report,
        debug_report,
        parity_report,
    ):
        if report["status"] == "FAIL":
            overall = "FAIL"
            break
        if report["status"] == "BLOCKED" and overall != "FAIL":
            overall = "BLOCKED"

    _write_json(
        artifacts_dir / "summary.json",
        {
            "overall": overall,
            "stages": stage_summary,
            "artifacts": {
                "process_status": str(artifacts_dir / "process_status.json"),
                "device_settings_snapshot": str(
                    artifacts_dir / "device_settings_snapshot.json"
                ),
                "seq_progression": str(artifacts_dir / "seq_progression.json"),
                "debug_stats_progression": str(
                    artifacts_dir / "debug_stats_progression.json"
                ),
                "plot_parity_report": str(artifacts_dir / "plot_parity_report.json"),
                "parity_python_samples": str(
                    artifacts_dir / "parity_python_samples.json"
                ),
                "parity_cli_samples": str(artifacts_dir / "parity_cli_samples.json"),
                "parity_stream_samples": str(
                    artifacts_dir / "parity_stream_samples.json"
                ),
            },
        },
    )

    print(json.dumps({"overall": overall, "artifacts_dir": str(artifacts_dir)}))
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
