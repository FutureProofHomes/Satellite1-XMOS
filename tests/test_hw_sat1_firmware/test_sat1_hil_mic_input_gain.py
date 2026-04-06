import json
import math
import os
import shlex
import statistics
import struct
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from typing import Sequence, cast

import pytest

from tests.conftest import PROJ_ROOT
from tests.test_doa.conftest import fixture_wav_required


Q30_UNITY = 0x40000000
Q30_LOW = 0x08000000
REF_SOURCE_LEGACY_DOWNSAMPLED = 0
MIC_SOURCE_PACKAGED_INPUT = 1
MIC_OUTPUT_BASE_CH = 4
REF_OUTPUT_CH_MAP = (2, 3)
PACKAGED_INPUT_SKIP_SYNC_MAP = [1, 2, 3, 4]
UPSAMPLE_CHANNEL_MAP_DEFAULT = [0, 1, 2, 3, 4, 5]
MIC_GAIN_CAPTURE_SEC = int(os.getenv("SAT1_HIL_MIC_GAIN_CAPTURE_SEC", "1"))
MIC_GAIN_RECORD_SECONDS = int(os.getenv("SAT1_HIL_MIC_GAIN_RECORD_SECONDS", "3"))
MIC_GAIN_WARMUP_SEC = float(os.getenv("SAT1_HIL_MIC_GAIN_WARMUP_SEC", "0.4"))
MIC_GAIN_MIN_RATIO = float(os.getenv("SAT1_HIL_MIC_GAIN_MIN_RATIO", "1.05"))
MIC_GAIN_MAX_PEAK = int(os.getenv("SAT1_HIL_MIC_GAIN_MAX_PEAK", str(0x70000000)))
MIC_GAIN_TEST_HIGH = int(os.getenv("SAT1_HIL_MIC_GAIN_TEST_HIGH", str(0x20000000)))
SAT1_HIL_APLAY_DEV = os.getenv("SAT1_HIL_APLAY_DEV", "hw:0,0")
SAT1_HIL_ARECORD_DEV = os.getenv("SAT1_HIL_ARECORD_DEV", "hw:0,1")
SAT1_HIL_REMOTE_AUDIO_DIR = os.getenv(
    "SAT1_RPI_SD_DIR", "/home/pi/.cache/sat1_wav_bench"
)
MIC_GAIN_FIXTURE_USE_DEDICATED = bool(
    int(os.getenv("SAT1_HIL_MIC_GAIN_USE_DEDICATED_FIXTURE", "1"))
)
MIC_GAIN_FIXTURE_ANGLE_DEG = float(
    os.getenv("SAT1_HIL_MIC_GAIN_FIXTURE_ANGLE_DEG", "45")
)
MIC_GAIN_SIGNAL_MIN_RMS = float(os.getenv("SAT1_HIL_MIC_GAIN_SIGNAL_MIN_RMS", "10.0"))
MIC_GAIN_SIGNAL_WAIT_TIMEOUT_S = float(
    os.getenv("SAT1_HIL_MIC_GAIN_SIGNAL_WAIT_TIMEOUT_S", "3.0")
)
MIC_GAIN_SIGNAL_CHECK_DURATION_S = float(
    os.getenv("SAT1_HIL_MIC_GAIN_SIGNAL_CHECK_DURATION_S", "0.1")
)
MIC_GAIN_DECODER_SYNC_WAIT_S = float(
    os.getenv("SAT1_HIL_MIC_GAIN_DECODER_SYNC_WAIT_S", "0.02")
)
MIC_GAIN_ANALYZE_WINDOW_MS = int(
    os.getenv("SAT1_HIL_MIC_GAIN_ANALYZE_WINDOW_MS", "100")
)
MIC_GAIN_ANALYZE_HOP_MS = int(os.getenv("SAT1_HIL_MIC_GAIN_ANALYZE_HOP_MS", "50"))
MIC_GAIN_EXPECTED_TOL = float(os.getenv("SAT1_HIL_MIC_GAIN_EXPECTED_TOL", "0.25"))
I2S_RATE_HZ = 48000
PIPELINE_RATE_HZ = 16000
UPSAMPLE_FACTOR = I2S_RATE_HZ // PIPELINE_RATE_HZ
SSH_CONNECT_TIMEOUT_S = int(os.getenv("SAT1_HIL_SSH_CONNECT_TIMEOUT_S", "5"))
SSH_CMD_TIMEOUT_S = int(os.getenv("SAT1_HIL_SSH_TIMEOUT_S", "30"))
REMOTE_CLI_TIMEOUT_S = int(os.getenv("SAT1_HIL_REMOTE_SDK_TIMEOUT_S", "40"))
RETRY_ATTEMPTS = int(os.getenv("SAT1_HIL_RETRY_ATTEMPTS", "4"))
RETRY_DELAY_S = float(os.getenv("SAT1_HIL_RETRY_DELAY_S", "0.5"))


def _run_ssh(
    host: str, cmd: str, timeout: int = SSH_CMD_TIMEOUT_S
) -> subprocess.CompletedProcess[str]:
    t0 = time.monotonic()
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={SSH_CONNECT_TIMEOUT_S}",
            host,
            cmd,
        ],
        cwd=PROJ_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    elapsed = time.monotonic() - t0
    if os.getenv("SAT1_HIL_TIMING", ""):
        print(f"[TIMING] ssh: {cmd[:50]:<50} -> {elapsed:.3f}s")
    return result


def _run_remote_cli_json(
    host: str, sat1_rpi_sat1_cmd: str, cmd: str, timeout: int = REMOTE_CLI_TIMEOUT_S
) -> dict:
    t0 = time.monotonic()
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(RETRY_ATTEMPTS):
        last = _run_ssh(host, f"{sat1_rpi_sat1_cmd} xmos {cmd}", timeout=timeout)
        if last.returncode == 0:
            out = last.stdout.strip()
            if out:
                elapsed = time.monotonic() - t0
                if os.getenv("SAT1_HIL_TIMING", ""):
                    print(f"[TIMING] cli_json: {cmd[:40]:<40} -> {elapsed:.3f}s")
                return json.loads(out.splitlines()[-1])
        if attempt < (RETRY_ATTEMPTS - 1):
            time.sleep(RETRY_DELAY_S)

    assert last is not None
    assert last.returncode == 0, last.stdout + last.stderr
    raise AssertionError("Expected JSON output from remote CLI command")


def _get_audio_settings(sat1_rpi_host: str, sat1_rpi_sat1_cmd: str) -> dict:
    return _run_remote_cli_json(
        sat1_rpi_host,
        sat1_rpi_sat1_cmd,
        "get-mic-pipeline-settings --json",
        timeout=REMOTE_CLI_TIMEOUT_S,
    )


def _set_mic_input_gains(
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
    *,
    mic_gain: int | None = None,
    ref_gain: int | None = None,
    ref_source_mode: int | None = None,
    mic_source_mode: int | None = None,
    mic_input_channel_map: list[int] | None = None,
) -> None:
    t0 = time.monotonic()
    mic_input = {
        "mic_gain": mic_gain,
        "ref_gain": ref_gain,
        "ref_source_mode": ref_source_mode,
        "mic_source_mode": mic_source_mode,
        "mic_input_channel_map": mic_input_channel_map,
    }
    payload = {"mic_input": {k: v for k, v in mic_input.items() if v is not None}}
    cmd = (
        "set-mic-pipeline-settings --json "
        f"{shlex.quote(json.dumps(payload, separators=(',', ':')))}"
    )
    res = _run_ssh(
        sat1_rpi_host, f"{sat1_rpi_sat1_cmd} xmos {cmd}", timeout=REMOTE_CLI_TIMEOUT_S
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "True" in res.stdout, res.stdout + res.stderr
    elapsed = time.monotonic() - t0
    if os.getenv("SAT1_HIL_TIMING", ""):
        mic_str = f"{mic_gain:#x}" if mic_gain is not None else "None"
        ref_str = f"{ref_gain:#x}" if ref_gain is not None else "None"
        desc = f"gain mic={mic_str} ref={ref_str}".ljust(35)
        print(f"[TIMING] set_gains: {desc} -> {elapsed:.3f}s")


def _set_mic_output_channels(
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
    left: int,
    right: int,
) -> None:
    t0 = time.monotonic()
    payload = {"mic_output": {"i2s_channel_map": [int(left), int(right)]}}
    cmd = (
        "set-mic-pipeline-settings --json "
        f"{shlex.quote(json.dumps(payload, separators=(',', ':')))}"
    )
    res = _run_ssh(
        sat1_rpi_host, f"{sat1_rpi_sat1_cmd} xmos {cmd}", timeout=REMOTE_CLI_TIMEOUT_S
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "True" in res.stdout, res.stdout + res.stderr
    elapsed = time.monotonic() - t0
    if os.getenv("SAT1_HIL_TIMING", ""):
        print(f"[TIMING] set_out_ch: left={left} right={right} -> {elapsed:.3f}s")


def _set_mic_output_packing(
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
    *,
    enabled: bool,
    upsample_channel_map: list[int] | None = None,
) -> None:
    t0 = time.monotonic()
    mic_output: dict[str, object] = {
        "pack_extra_upsample_channels": int(bool(enabled)),
    }
    if upsample_channel_map is not None:
        mic_output["upsample_channel_map"] = [int(v) for v in upsample_channel_map]
    payload = {"mic_output": mic_output}
    cmd = (
        "set-mic-pipeline-settings --json "
        f"{shlex.quote(json.dumps(payload, separators=(',', ':')))}"
    )
    res = _run_ssh(
        sat1_rpi_host, f"{sat1_rpi_sat1_cmd} xmos {cmd}", timeout=REMOTE_CLI_TIMEOUT_S
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "True" in res.stdout, res.stdout + res.stderr
    elapsed = time.monotonic() - t0
    if os.getenv("SAT1_HIL_TIMING", ""):
        print(f"[TIMING] set_packing: enabled={enabled} -> {elapsed:.3f}s")


def _run_remote_cli(
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
    args: list[str],
    *,
    timeout: int = REMOTE_CLI_TIMEOUT_S,
) -> subprocess.CompletedProcess[str]:
    cmd = " ".join(shlex.quote(part) for part in [sat1_rpi_sat1_cmd, "xmos", *args])
    res = _run_ssh(sat1_rpi_host, cmd, timeout=timeout)
    assert res.returncode == 0, res.stdout + res.stderr
    return res


def _set_mic_output_channels_cli(
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
    left: int,
    right: int,
) -> None:
    _run_remote_cli(
        sat1_rpi_host,
        sat1_rpi_sat1_cmd,
        ["set-mic-output", str(int(left)), str(int(right))],
    )


def _set_mic_gain_cli(
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
    mic_gain: int,
) -> None:
    _run_remote_cli(
        sat1_rpi_host,
        sat1_rpi_sat1_cmd,
        ["set-mic-input-gains", "--mic-gain", str(int(mic_gain))],
    )


def _set_mic_input_routing_cli(
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
    *,
    ref_source_mode: int,
    mic_source_mode: int,
    mic_input_channel_map: list[int],
) -> None:
    _run_remote_cli(
        sat1_rpi_host,
        sat1_rpi_sat1_cmd,
        [
            "set-mic-input-routing",
            "--ref-source-mode",
            str(int(ref_source_mode)),
            "--mic-source-mode",
            str(int(mic_source_mode)),
            "--mic-input-channel-map",
            *[str(int(v)) for v in mic_input_channel_map],
        ],
    )


def _log_remote_mic_settings(
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
) -> None:
    mic_input = _run_remote_cli(
        sat1_rpi_host,
        sat1_rpi_sat1_cmd,
        ["get-mic-input-settings"],
    )
    mic_output_cmd = " ".join(
        shlex.quote(part)
        for part in [sat1_rpi_sat1_cmd, "xmos", "get-mic-output-settings"]
    )
    mic_output = _run_ssh(sat1_rpi_host, mic_output_cmd, timeout=REMOTE_CLI_TIMEOUT_S)
    if mic_output.returncode != 0:
        mic_output_cmd = " ".join(
            shlex.quote(part)
            for part in [
                sat1_rpi_sat1_cmd,
                "xmos",
                "get-mic-pipeline-settings",
                "--json",
            ]
        )
        mic_output = _run_ssh(
            sat1_rpi_host, mic_output_cmd, timeout=REMOTE_CLI_TIMEOUT_S
        )
    if mic_input.stdout.strip():
        print(f"mic_input_settings: {mic_input.stdout.strip()}")
    if mic_output.stdout.strip():
        print(f"mic_output_settings: {mic_output.stdout.strip()}")


def _ensure_remote_dir(sat1_rpi_host: str, remote_dir: str) -> None:
    res = _run_ssh(
        sat1_rpi_host,
        f"/bin/sh -lc {shlex.quote(f'mkdir -p {shlex.quote(remote_dir)}')}",
        timeout=10,
    )
    assert res.returncode == 0, res.stdout + res.stderr


def _copy_file_to_remote(
    sat1_rpi_host: str,
    local_path: Path,
    *,
    remote_dir: str = SAT1_HIL_REMOTE_AUDIO_DIR,
) -> str:
    _ensure_remote_dir(sat1_rpi_host, remote_dir)
    remote_path = f"{remote_dir}/{local_path.name}"
    scp_res = subprocess.run(
        ["scp", str(local_path), f"{sat1_rpi_host}:{remote_path}"],
        cwd=PROJ_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert scp_res.returncode == 0, scp_res.stdout + scp_res.stderr
    return remote_path


def _download_file_from_remote(
    sat1_rpi_host: str,
    remote_path: str,
    local_path: Path,
) -> None:
    scp_res = subprocess.run(
        ["scp", f"{sat1_rpi_host}:{remote_path}", str(local_path)],
        cwd=PROJ_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert scp_res.returncode == 0, scp_res.stdout + scp_res.stderr


def _start_remote_wav_record_once(
    sat1_rpi_host: str,
    remote_wav: str,
    *,
    record_seconds: int = MIC_GAIN_RECORD_SECONDS,
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            "ssh",
            sat1_rpi_host,
            (
                f"arecord -q -c 2 -r {I2S_RATE_HZ} -f S32_LE "
                f"-D {shlex.quote(SAT1_HIL_ARECORD_DEV)} "
                f"-d {record_seconds} {shlex.quote(remote_wav)}"
            ),
        ],
        cwd=PROJ_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _start_remote_wav_playback_once(
    sat1_rpi_host: str,
    remote_wav: str,
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            "ssh",
            sat1_rpi_host,
            (
                f"aplay -q -c 2 -D {shlex.quote(SAT1_HIL_APLAY_DEV)} "
                f"{shlex.quote(remote_wav)}"
            ),
        ],
        cwd=PROJ_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _finish_remote_audio_proc(
    proc: subprocess.Popen[bytes],
    *,
    label: str,
    timeout_s: float,
) -> None:
    try:
        returncode = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        proc.wait(timeout=3)
        raise AssertionError(f"{label} timed out after {timeout_s}s") from exc

    if returncode != 0:
        stderr = b""
        if proc.stderr is not None:
            stderr = proc.stderr.read()
        raise AssertionError(
            f"{label} failed: {stderr.decode('utf-8', errors='replace').strip()}"
        )


def _stop_remote_audio_proc(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None or proc.poll() is not None:
        return

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def _cleanup_remote_files(sat1_rpi_host: str, *paths: str) -> None:
    quoted = " ".join(shlex.quote(path) for path in paths if path)
    if not quoted:
        return
    _run_ssh(sat1_rpi_host, f"rm -f {quoted}", timeout=10)


def _decode_pcm(raw: bytes, sample_width: int) -> list[float]:
    if sample_width == 2:
        step = 2
    elif sample_width == 3:
        step = 3
    elif sample_width == 4:
        step = 4
    else:
        raise ValueError(f"unsupported sample width: {sample_width}")

    out = []
    for i in range(0, len(raw), step):
        if sample_width == 2:
            val = int.from_bytes(raw[i : i + 2], "little", signed=True)
        elif sample_width == 3:
            b0 = raw[i]
            b1 = raw[i + 1]
            b2 = raw[i + 2]
            val = b0 | (b1 << 8) | (b2 << 16)
            if val & 0x800000:
                val -= 1 << 24
        else:
            val = int.from_bytes(raw[i : i + 4], "little", signed=True)
        out.append(float(val))
    return out


def _load_wav_channel(wav_path: Path, channel: int) -> tuple[list[float], int]:
    with wave.open(str(wav_path), "rb") as wf:
        num_channels = wf.getnchannels()
        rate_hz = wf.getframerate()
        sample_width = wf.getsampwidth()
        num_frames = wf.getnframes()
        if channel < 0 or channel >= num_channels:
            raise ValueError(f"channel must be in range 0-{num_channels - 1}")
        raw = wf.readframes(num_frames)

    samples = _decode_pcm(raw, sample_width)
    return samples[channel::num_channels], rate_hz


def _load_packed_wav_lane(wav_path: Path, lane: int) -> tuple[list[float], int]:
    with wave.open(str(wav_path), "rb") as wf:
        num_channels = wf.getnchannels()
        rate_hz = wf.getframerate()
        sample_width = wf.getsampwidth()
        num_frames = wf.getnframes()
        assert num_channels == 2, f"expected stereo WAV, got {num_channels} channels"
        assert rate_hz == I2S_RATE_HZ, f"expected 48kHz WAV, got {rate_hz}"
        raw = wf.readframes(num_frames)

    if lane < 1 or lane > 4:
        raise ValueError("lane must be in range 1-4")

    samples = _decode_pcm(raw, sample_width)
    left = samples[0::2]
    right = samples[1::2]
    if lane in (1, 2):
        signal = left[lane::UPSAMPLE_FACTOR]
    else:
        signal = right[lane - 3 :: UPSAMPLE_FACTOR]
    return signal, PIPELINE_RATE_HZ


def _rms_window_stats(
    samples: list[float],
    rate_hz: int,
    window_ms: int,
    hop_ms: int,
) -> dict[str, float | list[float] | int] | None:
    window = max(1, int(rate_hz * (window_ms / 1000.0)))
    hop = max(1, int(rate_hz * (hop_ms / 1000.0)))
    rms_vals = []
    for start in range(0, max(0, len(samples) - window + 1), hop):
        segment = samples[start : start + window]
        if segment:
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


def _estimate_gain_from_recording(
    *,
    injected_path: Path,
    recorded_path: Path,
    packed_lane: int,
    recorded_channel: int = 0,
    window_ms: int = MIC_GAIN_ANALYZE_WINDOW_MS,
    hop_ms: int = MIC_GAIN_ANALYZE_HOP_MS,
) -> dict[str, float]:
    injected_signal, injected_rate = _load_packed_wav_lane(injected_path, packed_lane)
    recorded_signal, recorded_rate = _load_wav_channel(recorded_path, recorded_channel)
    recorded_peak = max(abs(v) for v in recorded_signal)

    if recorded_rate == I2S_RATE_HZ and injected_rate == PIPELINE_RATE_HZ:
        recorded_signal = recorded_signal[::UPSAMPLE_FACTOR]
        recorded_rate = PIPELINE_RATE_HZ

    injected_stats = _rms_window_stats(
        injected_signal, injected_rate, window_ms, hop_ms
    )
    recorded_stats = _rms_window_stats(
        recorded_signal, recorded_rate, window_ms, hop_ms
    )
    assert injected_stats is not None, "Expected injected RMS stats"
    assert recorded_stats is not None, "Expected recorded RMS stats"

    injected_p50 = cast(
        float, injected_stats["active_p50"] or injected_stats["rms_p50"]
    )
    recorded_p50 = cast(
        float, recorded_stats["active_p50"] or recorded_stats["rms_p50"]
    )
    assert injected_p50 > 0, "Expected non-zero injected RMS"

    return {
        "estimate": recorded_p50 / injected_p50,
        "injected_active_p50": injected_p50,
        "recorded_active_p50": recorded_p50,
        "recorded_peak": float(recorded_peak),
    }


def _estimate_recorded_level(
    *,
    recorded_path: Path,
    recorded_channel: int = 0,
    window_ms: int = MIC_GAIN_ANALYZE_WINDOW_MS,
    hop_ms: int = MIC_GAIN_ANALYZE_HOP_MS,
) -> dict[str, float]:
    recorded_signal, recorded_rate = _load_wav_channel(recorded_path, recorded_channel)
    recorded_peak = max(abs(v) for v in recorded_signal)

    recorded_stats = _rms_window_stats(
        recorded_signal, recorded_rate, window_ms, hop_ms
    )
    assert recorded_stats is not None, "Expected recorded RMS stats"
    recorded_p50 = cast(
        float, recorded_stats["active_p50"] or recorded_stats["rms_p50"]
    )
    return {
        "recorded_active_p50": recorded_p50,
        "recorded_peak": float(recorded_peak),
    }


def _assert_gain_estimate(
    *,
    label: str,
    mic_idx: int,
    estimate: float,
    expected: float,
    peak: int,
) -> None:
    assert peak < MIC_GAIN_MAX_PEAK, (
        f"Recording clipped (mic_idx={mic_idx}, peak={peak})"
    )
    assert estimate > 0.0, (
        f"Expected positive gain estimate (mic_idx={mic_idx}, estimate={estimate:.4f})"
    )
    if expected > 0:
        rel_err = abs(estimate - expected) / expected
        assert rel_err <= MIC_GAIN_EXPECTED_TOL, (
            f"{label} gain estimate out of tolerance (mic_idx={mic_idx}, "
            f"estimate={estimate:.4f}, expected={expected:.4f}, "
            f"rel_err={rel_err:.3f}, tol={MIC_GAIN_EXPECTED_TOL:.3f})"
        )


def _measure_mic_gain_recording(
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
    *,
    injected_path: Path,
    remote_injected_path: str,
    mic_idx: int,
    mic_gain: int,
) -> dict[str, float]:
    target_output_ch = MIC_OUTPUT_BASE_CH + mic_idx
    remote_recorded_path = (
        f"{SAT1_HIL_REMOTE_AUDIO_DIR}/recorded_{injected_path.stem}_"
        f"mic{mic_idx}_{mic_gain}_{int(time.time() * 1_000_000)}.wav"
    )

    _set_mic_output_packing(
        sat1_rpi_host,
        sat1_rpi_sat1_cmd,
        enabled=False,
    )
    _set_mic_output_channels_cli(
        sat1_rpi_host,
        sat1_rpi_sat1_cmd,
        target_output_ch,
        target_output_ch,
    )
    _set_mic_gain_cli(sat1_rpi_host, sat1_rpi_sat1_cmd, mic_gain)
    _log_remote_mic_settings(sat1_rpi_host, sat1_rpi_sat1_cmd)
    _set_mic_input_routing_cli(
        sat1_rpi_host,
        sat1_rpi_sat1_cmd,
        ref_source_mode=REF_SOURCE_LEGACY_DOWNSAMPLED,
        mic_source_mode=MIC_SOURCE_PACKAGED_INPUT,
        mic_input_channel_map=PACKAGED_INPUT_SKIP_SYNC_MAP,
    )

    record_proc = _start_remote_wav_record_once(
        sat1_rpi_host,
        remote_recorded_path,
        record_seconds=MIC_GAIN_RECORD_SECONDS,
    )
    play_proc: subprocess.Popen[bytes] | None = None
    try:
        play_proc = _start_remote_wav_playback_once(sat1_rpi_host, remote_injected_path)
        _finish_remote_audio_proc(
            play_proc,
            label="aplay",
            timeout_s=MIC_GAIN_RECORD_SECONDS + 20,
        )
        _finish_remote_audio_proc(
            record_proc,
            label="arecord",
            timeout_s=MIC_GAIN_RECORD_SECONDS + 20,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            local_recorded_path = Path(tmpdir) / Path(remote_recorded_path).name
            _download_file_from_remote(
                sat1_rpi_host,
                remote_recorded_path,
                local_recorded_path,
            )
            return _estimate_gain_from_recording(
                injected_path=injected_path,
                recorded_path=local_recorded_path,
                packed_lane=mic_idx + 1,
            )
    finally:
        _stop_remote_audio_proc(play_proc)
        _stop_remote_audio_proc(record_proc)
        _cleanup_remote_files(sat1_rpi_host, remote_recorded_path)


def _measure_mic_gain_recording_pair(
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
    *,
    injected_path: Path,
    remote_injected_path: str,
    mic_left: int,
    mic_right: int,
    mic_gain: int,
) -> dict[str, dict[str, float]]:
    left_output_ch = MIC_OUTPUT_BASE_CH + mic_left
    right_output_ch = MIC_OUTPUT_BASE_CH + mic_right
    remote_recorded_path = (
        f"{SAT1_HIL_REMOTE_AUDIO_DIR}/recorded_{injected_path.stem}_"
        f"mic{mic_left}-{mic_right}_{mic_gain}_{int(time.time() * 1_000_000)}.wav"
    )

    _set_mic_output_packing(
        sat1_rpi_host,
        sat1_rpi_sat1_cmd,
        enabled=False,
    )
    _set_mic_output_channels_cli(
        sat1_rpi_host,
        sat1_rpi_sat1_cmd,
        left_output_ch,
        right_output_ch,
    )
    _set_mic_gain_cli(sat1_rpi_host, sat1_rpi_sat1_cmd, mic_gain)
    _log_remote_mic_settings(sat1_rpi_host, sat1_rpi_sat1_cmd)
    _set_mic_input_routing_cli(
        sat1_rpi_host,
        sat1_rpi_sat1_cmd,
        ref_source_mode=REF_SOURCE_LEGACY_DOWNSAMPLED,
        mic_source_mode=MIC_SOURCE_PACKAGED_INPUT,
        mic_input_channel_map=PACKAGED_INPUT_SKIP_SYNC_MAP,
    )

    record_proc = _start_remote_wav_record_once(
        sat1_rpi_host,
        remote_recorded_path,
        record_seconds=MIC_GAIN_RECORD_SECONDS,
    )
    play_proc: subprocess.Popen[bytes] | None = None
    try:
        play_proc = _start_remote_wav_playback_once(sat1_rpi_host, remote_injected_path)
        _finish_remote_audio_proc(
            play_proc,
            label="aplay",
            timeout_s=MIC_GAIN_RECORD_SECONDS + 20,
        )
        _finish_remote_audio_proc(
            record_proc,
            label="arecord",
            timeout_s=MIC_GAIN_RECORD_SECONDS + 20,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            local_recorded_path = Path(tmpdir) / Path(remote_recorded_path).name
            _download_file_from_remote(
                sat1_rpi_host,
                remote_recorded_path,
                local_recorded_path,
            )
            left = _estimate_gain_from_recording(
                injected_path=injected_path,
                recorded_path=local_recorded_path,
                packed_lane=mic_left + 1,
                recorded_channel=0,
            )
            right = _estimate_gain_from_recording(
                injected_path=injected_path,
                recorded_path=local_recorded_path,
                packed_lane=mic_right + 1,
                recorded_channel=1,
            )
            return {"left": left, "right": right}
    finally:
        _stop_remote_audio_proc(play_proc)
        _stop_remote_audio_proc(record_proc)
        _cleanup_remote_files(sat1_rpi_host, remote_recorded_path)


def _measure_ref_gain_recording_pair(
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
    *,
    remote_injected_path: str,
    ref_gain: int,
) -> dict[str, dict[str, float]]:
    remote_recorded_path = f"{SAT1_HIL_REMOTE_AUDIO_DIR}/recorded_ref_{ref_gain}_{int(time.time() * 1_000_000)}.wav"

    _set_mic_output_packing(
        sat1_rpi_host,
        sat1_rpi_sat1_cmd,
        enabled=False,
    )
    _set_mic_output_channels_cli(
        sat1_rpi_host,
        sat1_rpi_sat1_cmd,
        REF_OUTPUT_CH_MAP[0],
        REF_OUTPUT_CH_MAP[1],
    )
    _set_mic_input_gains(
        sat1_rpi_host,
        sat1_rpi_sat1_cmd,
        mic_gain=Q30_UNITY,
        ref_gain=ref_gain,
        ref_source_mode=REF_SOURCE_LEGACY_DOWNSAMPLED,
        mic_source_mode=MIC_SOURCE_PACKAGED_INPUT,
        mic_input_channel_map=PACKAGED_INPUT_SKIP_SYNC_MAP,
    )
    _log_remote_mic_settings(sat1_rpi_host, sat1_rpi_sat1_cmd)

    record_proc = _start_remote_wav_record_once(
        sat1_rpi_host,
        remote_recorded_path,
        record_seconds=MIC_GAIN_RECORD_SECONDS,
    )
    play_proc: subprocess.Popen[bytes] | None = None
    try:
        play_proc = _start_remote_wav_playback_once(sat1_rpi_host, remote_injected_path)
        _finish_remote_audio_proc(
            play_proc,
            label="aplay",
            timeout_s=MIC_GAIN_RECORD_SECONDS + 20,
        )
        _finish_remote_audio_proc(
            record_proc,
            label="arecord",
            timeout_s=MIC_GAIN_RECORD_SECONDS + 20,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            local_recorded_path = Path(tmpdir) / Path(remote_recorded_path).name
            _download_file_from_remote(
                sat1_rpi_host,
                remote_recorded_path,
                local_recorded_path,
            )
            left = _estimate_recorded_level(
                recorded_path=local_recorded_path,
                recorded_channel=0,
            )
            right = _estimate_recorded_level(
                recorded_path=local_recorded_path,
                recorded_channel=1,
            )
            return {"left": left, "right": right}
    finally:
        _stop_remote_audio_proc(play_proc)
        _stop_remote_audio_proc(record_proc)
        _cleanup_remote_files(sat1_rpi_host, remote_recorded_path)


def _capture_channel_samples(
    sat1_rpi_host: str,
    *,
    duration_s: float = 2,
    channel_index: int = 0,
) -> list[int]:
    t0 = time.monotonic()
    # arecord -d expects integer seconds only
    duration_int = max(1, int(math.ceil(duration_s)))
    capture_cmd = (
        f"arecord -D hw:0,1 -f S32_LE -r {I2S_RATE_HZ} -c 2 -d {duration_int} -t raw -q"
    )
    res = subprocess.run(
        ["ssh", sat1_rpi_host, capture_cmd],
        cwd=PROJ_ROOT,
        check=False,
        capture_output=True,
        timeout=duration_s + 20,
    )
    assert res.returncode == 0, res.stderr.decode("utf-8", errors="replace")

    samples = [v[0] for v in struct.iter_unpack("<i", res.stdout)]
    assert samples, "Expected captured PCM samples"

    selected = samples[channel_index::2]
    assert selected, "Expected channel samples in capture"

    elapsed = time.monotonic() - t0
    if os.getenv("SAT1_HIL_TIMING", ""):
        print(
            f"[TIMING] arecord: {duration_s:.1f}s cap -> {elapsed:.3f}s ({len(selected)} samples)"
        )
    return selected


def _extract_pipeline_rate_lane(samples_48k: list[int], lane: int = 0) -> list[int]:
    assert UPSAMPLE_FACTOR == 3
    assert 0 <= lane < UPSAMPLE_FACTOR

    lane_samples = samples_48k[lane::UPSAMPLE_FACTOR]
    assert lane_samples, "Expected extracted pipeline-rate samples"
    return lane_samples


def _rms(samples: Sequence[float | int]) -> float:
    assert samples, "Expected non-empty sample list"

    acc = 0
    for s in samples:
        acc += s * s

    return math.sqrt(acc / len(samples))


def _capture_rms(
    sat1_rpi_host: str,
    *,
    duration_s: int = 2,
    channel_index: int = 0,
    lane: int = 0,
) -> float:
    channel_samples = _capture_channel_samples(
        sat1_rpi_host,
        duration_s=duration_s,
        channel_index=channel_index,
    )
    pipeline_samples = _extract_pipeline_rate_lane(channel_samples, lane=lane)
    return _rms(pipeline_samples)


def _capture_rms_fullband(
    sat1_rpi_host: str,
    *,
    duration_s: float = 2,
    channel_index: int = 0,
) -> tuple[float, int]:
    channel_samples = _capture_channel_samples(
        sat1_rpi_host,
        duration_s=duration_s,
        channel_index=channel_index,
    )
    peak = max(abs(v) for v in channel_samples)
    return _rms(channel_samples), peak


def _capture_rms_median_fullband(
    sat1_rpi_host: str,
    *,
    repeats: int,
    duration_s: int,
    channel_index: int = 0,
) -> tuple[float, int]:
    rms_values: list[float] = []
    peak = 0
    for _ in range(repeats):
        rms, capture_peak = _capture_rms_fullband(
            sat1_rpi_host,
            duration_s=duration_s,
            channel_index=channel_index,
        )
        rms_values.append(rms)
        peak = max(peak, capture_peak)
    return statistics.median(rms_values), peak


def _start_remote_wav_playback_loop(
    sat1_rpi_host: str,
    remote_wav: str,
) -> subprocess.Popen[bytes]:
    """Start looping WAV playback.

    Uses infinite loop to ensure signal persists throughout the entire test.
    The fixture is short enough that loop-restart jitter is negligible.
    """
    return subprocess.Popen(
        [
            "ssh",
            sat1_rpi_host,
            (
                "sh -c "
                + shlex.quote(
                    "while true; do "
                    f"aplay -D {SAT1_HIL_APLAY_DEV} -f S32_LE -r {I2S_RATE_HZ} -c 2 "
                    f"{shlex.quote(remote_wav)} >/dev/null 2>&1; "
                    "done"
                )
            ),
        ],
        cwd=PROJ_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for_signal(
    sat1_rpi_host: str,
    min_rms: float = MIC_GAIN_SIGNAL_MIN_RMS,
    timeout_s: float = MIC_GAIN_SIGNAL_WAIT_TIMEOUT_S,
    check_duration_s: float = MIC_GAIN_SIGNAL_CHECK_DURATION_S,
) -> float:
    """Block until captured signal exceeds minimum RMS threshold.

    This ensures playback has started and the packaged decoder has locked
    onto valid input before proceeding with measurements.

    Args:
        sat1_rpi_host: SSH host for SAT1 Pi
        min_rms: Minimum RMS threshold to consider signal present
        timeout_s: Maximum time to wait for signal
        check_duration_s: Duration of each probe capture

    Returns:
        The RMS value when signal was detected

    Raises:
        RuntimeError: If no valid signal detected within timeout
    """
    t0 = time.monotonic()
    attempts = 0
    while time.monotonic() - t0 < timeout_s:
        attempts += 1
        rms, _ = _capture_rms_fullband(sat1_rpi_host, duration_s=check_duration_s)
        if rms >= min_rms:
            elapsed = time.monotonic() - t0
            if os.getenv("SAT1_HIL_TIMING", ""):
                print(
                    f"[TIMING] wait_signal: {attempts} attempts -> {elapsed:.3f}s (RMS={rms:.1f})"
                )
            return rms
        time.sleep(0.02)  # Small delay between probes

    elapsed = time.monotonic() - t0
    raise RuntimeError(
        f"No signal detected (RMS<{min_rms}) within {timeout_s}s "
        f"(waited {elapsed:.2f}s, {attempts} attempts)"
    )


def _start_remote_tone(sat1_rpi_host: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            "ssh",
            sat1_rpi_host,
            "speaker-test -D hw:0,0 -t sine -f 1000",
        ],
        cwd=PROJ_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture
def audio_settings_guard(
    require_sat1_hil: None,
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
):
    original = _get_audio_settings(sat1_rpi_host, sat1_rpi_sat1_cmd)
    yield original

    _set_mic_input_gains(
        sat1_rpi_host,
        sat1_rpi_sat1_cmd,
        mic_gain=original["mic_input"]["mic_gain"],
        ref_gain=original["mic_input"]["ref_gain"],
        ref_source_mode=original["mic_input"]["ref_source_mode"],
        mic_source_mode=original["mic_input"]["mic_source_mode"],
        mic_input_channel_map=original["mic_input"]["mic_input_channel_map"],
    )
    _set_mic_output_channels(
        sat1_rpi_host,
        sat1_rpi_sat1_cmd,
        original["mic_output"]["i2s_channel_map"][0],
        original["mic_output"]["i2s_channel_map"][1],
    )
    _set_mic_output_packing(
        sat1_rpi_host,
        sat1_rpi_sat1_cmd,
        enabled=bool(original["mic_output"]["pack_extra_upsample_channels"]),
        upsample_channel_map=original["mic_output"]["upsample_channel_map"],
    )


@pytest.mark.hil
@pytest.mark.sat1
def test_mic_input_settings_shape_sat1(
    audio_settings_guard,
) -> None:
    settings = audio_settings_guard
    assert settings["available_mic_count"] >= 1
    assert len(settings["mic_input"]["ref_input_channel_map"]) == 2
    assert len(settings["mic_input"]["mic_input_channel_map"]) >= 2


@pytest.mark.hil
@pytest.mark.sat1
def test_mic_input_gain_roundtrip_sat1(
    audio_settings_guard,
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
) -> None:
    _set_mic_input_gains(
        sat1_rpi_host,
        sat1_rpi_sat1_cmd,
        mic_gain=0x18000000,
        ref_gain=0x10000000,
    )

    current = _get_audio_settings(sat1_rpi_host, sat1_rpi_sat1_cmd)
    assert current["mic_input"]["mic_gain"] == 0x18000000
    assert current["mic_input"]["ref_gain"] == 0x10000000


@pytest.mark.hil
@pytest.mark.sat1
@pytest.mark.parametrize(
    ("mic_left", "mic_right", "mic_gain"),
    [(0, 1, Q30_LOW), (2, 3, MIC_GAIN_TEST_HIGH)],
    ids=("mic_0_1_low", "mic_2_3_high"),
)
def test_mic_gain_changes_captured_level_sat1(
    audio_settings_guard,
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
    mic_left: int,
    mic_right: int,
    mic_gain: int,
) -> None:
    """Mirror ssh_mic_gain_measure.py for packaged-input mic-gain checks."""
    if MIC_GAIN_FIXTURE_USE_DEDICATED:
        local_wav = (
            PROJ_ROOT
            / "tests"
            / "test_doa"
            / "fixtures"
            / "lag_synth"
            / "mic_gain_test_fixture.wav"
        )
        if not local_wav.exists():
            raise FileNotFoundError(
                f"Dedicated mic-gain fixture not found: {local_wav}. "
                "Generate it with: python3 tools/doa/generate_mic_gain_fixture.py --output tests/test_doa/fixtures/lag_synth/mic_gain_test_fixture.wav"
            )
    else:
        local_wav = fixture_wav_required(MIC_GAIN_FIXTURE_ANGLE_DEG)
    local_wav = Path(local_wav)
    remote_wav = _copy_file_to_remote(sat1_rpi_host, local_wav)

    try:
        measures = _measure_mic_gain_recording_pair(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            injected_path=local_wav,
            remote_injected_path=remote_wav,
            mic_left=mic_left,
            mic_right=mic_right,
            mic_gain=mic_gain,
        )
    finally:
        _cleanup_remote_files(sat1_rpi_host, remote_wav)

    for label, mic_idx in (("left", mic_left), ("right", mic_right)):
        measure = measures[label]
        estimate = float(measure["estimate"])
        peak = int(measure["recorded_peak"])
        print(
            f"{label.upper()} gain: "
            f"estimate={estimate:.4f}, peak={peak}, mic_idx={mic_idx}, "
            f"recorded_p50={measure['recorded_active_p50']:.1f}, "
            f"injected_p50={measure['injected_active_p50']:.1f}"
        )
        expected = mic_gain / float(Q30_UNITY)
        _assert_gain_estimate(
            label=label,
            mic_idx=mic_idx,
            estimate=estimate,
            expected=expected,
            peak=peak,
        )


@pytest.mark.hil
@pytest.mark.sat1
def test_ref_gain_changes_captured_level_sat1(
    audio_settings_guard,
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
) -> None:
    local_wav = (
        PROJ_ROOT
        / "tests"
        / "test_doa"
        / "fixtures"
        / "lag_synth"
        / "mic_gain_test_fixture.wav"
    )
    if not local_wav.exists():
        raise FileNotFoundError(
            f"Dedicated mic-gain fixture not found: {local_wav}. "
            "Generate it with: python3 tools/doa/generate_mic_gain_fixture.py --output tests/test_doa/fixtures/lag_synth/mic_gain_test_fixture.wav"
        )
    local_wav = Path(local_wav)
    remote_wav = _copy_file_to_remote(sat1_rpi_host, local_wav)

    try:
        low = _measure_ref_gain_recording_pair(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            remote_injected_path=remote_wav,
            ref_gain=Q30_LOW,
        )
        high = _measure_ref_gain_recording_pair(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            remote_injected_path=remote_wav,
            ref_gain=Q30_UNITY,
        )
    finally:
        _cleanup_remote_files(sat1_rpi_host, remote_wav)

    expected_ratio = float(Q30_UNITY) / float(Q30_LOW)
    for label in ("left", "right"):
        low_level = float(low[label]["recorded_active_p50"])
        high_level = float(high[label]["recorded_active_p50"])
        low_peak = int(low[label]["recorded_peak"])
        high_peak = int(high[label]["recorded_peak"])
        print(
            f"REF {label.upper()}: "
            f"low_p50={low_level:.1f} high_p50={high_level:.1f} "
            f"low_peak={low_peak} high_peak={high_peak}"
        )
        assert low_peak < MIC_GAIN_MAX_PEAK, (
            f"Ref low-gain recording clipped (peak={low_peak})"
        )
        assert high_peak < MIC_GAIN_MAX_PEAK, (
            f"Ref high-gain recording clipped (peak={high_peak})"
        )
        assert low_level > 0.0, "Expected non-zero ref RMS at low gain"
        assert high_level > 0.0, "Expected non-zero ref RMS at high gain"
        ratio = high_level / low_level
        rel_err = abs(ratio - expected_ratio) / expected_ratio
        assert rel_err <= MIC_GAIN_EXPECTED_TOL, (
            f"Ref gain ratio out of tolerance ({label} ratio={ratio:.3f}, "
            f"expected={expected_ratio:.3f}, rel_err={rel_err:.3f}, "
            f"tol={MIC_GAIN_EXPECTED_TOL:.3f})"
        )
