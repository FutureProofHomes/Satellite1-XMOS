"""
Async HIL mic input gain tests using persistent SSH connections.

This module provides async versions of the mic gain tests that use
hil_utils.RemoteAudioSession for efficient audio playback/recording
over a single persistent SSH connection.
"""

import asyncio
import json
import math
import os
import shlex
import statistics
import struct
import time
import wave
from pathlib import Path
from typing import Sequence, cast

import pytest

from hil_utils import RemoteAudioSession, CmdResult
from tests.conftest import PROJ_ROOT
from tests.test_hil.conftest import I2S_INPUT_MODE_DOWNSAMPLED, I2S_INPUT_MODE_PACKAGED
from tests.test_doa.conftest import fixture_wav_required


# Constants
Q30_UNITY = 0x40000000
Q30_LOW = 0x08000000
REF_SOURCE_DOWNSAMPLED = I2S_INPUT_MODE_DOWNSAMPLED
MIC_SOURCE_PACKAGED_INPUT = I2S_INPUT_MODE_PACKAGED
MIC_OUTPUT_BASE_CH = 4
REF_OUTPUT_CH_MAP = (2, 3)
PACKAGED_INPUT_SKIP_SYNC_MAP = [1, 2, 3, 4]
UPSAMPLE_CHANNEL_MAP_DEFAULT = [0, 1, 2, 3, 4, 5]

# Configurable via environment
MIC_GAIN_CAPTURE_REPEATS = int(os.getenv("SAT1_HIL_MIC_GAIN_CAPTURE_REPEATS", "3"))
MIC_GAIN_CAPTURE_SEC = int(os.getenv("SAT1_HIL_MIC_GAIN_CAPTURE_SEC", "1"))
MIC_GAIN_WARMUP_SEC = float(os.getenv("SAT1_HIL_MIC_GAIN_WARMUP_SEC", "0.4"))
MIC_GAIN_MIN_RATIO = float(os.getenv("SAT1_HIL_MIC_GAIN_MIN_RATIO", "1.05"))
MIC_GAIN_MAX_PEAK = int(os.getenv("SAT1_HIL_MIC_GAIN_MAX_PEAK", str(0x70000000)))
MIC_GAIN_TEST_HIGH = int(os.getenv("SAT1_HIL_MIC_GAIN_TEST_HIGH", str(0x20000000)))
MIC_GAIN_RECORD_SECONDS = int(os.getenv("SAT1_HIL_MIC_GAIN_RECORD_SECONDS", "3"))
SAT1_HIL_APLAY_DEV = os.getenv("SAT1_HIL_APLAY_DEV", "hw:0,0")
SAT1_HIL_ARECORD_DEV = os.getenv("SAT1_HIL_ARECORD_DEV", "hw:0,1")
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
REMOTE_CLI_TIMEOUT_S = int(os.getenv("SAT1_HIL_REMOTE_SDK_TIMEOUT_S", "40"))
HIL_FIXTURE_DIR = PROJ_ROOT / "tests" / "test_hil" / "fixtures"
MIC_GAIN_FIXTURE_WAV = HIL_FIXTURE_DIR / "mic_gain_test_fixture.wav"


def _timing_enabled() -> bool:
    return bool(os.getenv("SAT1_HIL_TIMING", ""))


def _rms(samples: Sequence[float | int]) -> float:
    """Calculate RMS of sample list."""
    assert samples, "Expected non-empty sample list"
    acc = 0
    for s in samples:
        acc += s * s
    return math.sqrt(acc / len(samples))


def _decode_pcm(raw: bytes, sample_width: int) -> list[int]:
    if sample_width == 4:
        return [v[0] for v in struct.iter_unpack("<i", raw)]
    if sample_width == 2:
        return [v[0] for v in struct.iter_unpack("<h", raw)]
    raise ValueError(f"Unsupported PCM sample width {sample_width}")


def _load_wav_channel(path: Path, channel_index: int = 0) -> tuple[list[int], int]:
    with wave.open(str(path), "rb") as wf:
        num_channels = wf.getnchannels()
        rate_hz = wf.getframerate()
        sample_width = wf.getsampwidth()
        num_frames = wf.getnframes()
        assert num_channels == 2, f"expected stereo WAV, got {num_channels} channels"
        raw = wf.readframes(num_frames)

    samples = _decode_pcm(raw, sample_width)
    selected = samples[channel_index::2]
    assert selected, "Expected channel samples"
    return selected, rate_hz


def _load_packed_wav_lane(path: Path, lane: int) -> tuple[list[int], int]:
    with wave.open(str(path), "rb") as wf:
        num_channels = wf.getnchannels()
        rate_hz = wf.getframerate()
        sample_width = wf.getsampwidth()
        num_frames = wf.getnframes()
        assert num_channels == 2, f"expected stereo WAV, got {num_channels} channels"
        assert rate_hz == I2S_RATE_HZ, f"expected 48kHz WAV, got {rate_hz}"
        raw = wf.readframes(num_frames)

    if lane < 0 or lane > 5:
        raise ValueError("lane must be in range 0-5")

    samples = _decode_pcm(raw, sample_width)
    left = samples[0::2]
    right = samples[1::2]
    if lane < UPSAMPLE_FACTOR:
        signal = left[lane::UPSAMPLE_FACTOR]
    else:
        signal = right[lane - UPSAMPLE_FACTOR :: UPSAMPLE_FACTOR]
    return signal, PIPELINE_RATE_HZ


def _packaged_input_map_for_board(_: str | None = None) -> list[int]:
    return list(PACKAGED_INPUT_SKIP_SYNC_MAP)


def _rms_window_stats(
    samples: Sequence[float | int],
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
    assert estimate > 0.0, f"Expected positive gain estimate ({label})"
    rel_err = abs(estimate - expected) / expected
    assert rel_err <= MIC_GAIN_EXPECTED_TOL, (
        f"Gain estimate out of tolerance ({label} mic_idx={mic_idx}, "
        f"estimate={estimate:.4f}, expected={expected:.4f}, "
        f"rel_err={rel_err:.3f}, tol={MIC_GAIN_EXPECTED_TOL:.3f})"
    )


def _extract_samples_from_wav(wav_data: bytes, channel_index: int = 0) -> list[int]:
    """Extract PCM samples from WAV file data."""
    data_pos = wav_data.find(b"data")
    if data_pos == -1:
        audio_data = wav_data[44:]
    else:
        audio_data = wav_data[data_pos + 8 :]

    samples = [v[0] for v in struct.iter_unpack("<i", audio_data)]
    assert samples, "Expected captured PCM samples"
    selected = samples[channel_index::2]
    assert selected, "Expected channel samples in capture"
    return selected


async def _get_audio_settings(sess: RemoteAudioSession, sat1_cmd: str) -> dict:
    t0 = time.monotonic()
    result: CmdResult = await sess.cmd(
        f"{sat1_cmd} xmos get-mic-pipeline-settings --json",
        timeout=REMOTE_CLI_TIMEOUT_S,
    )
    if _timing_enabled():
        elapsed = time.monotonic() - t0
        print(f"[TIMING] cli: get-mic-pipeline-settings -> {elapsed:.3f}s")

    assert result.exit_status == 0, f"CLI failed: {result.stderr}"
    out = result.stdout if isinstance(result.stdout, str) else result.stdout.decode()
    out = out.strip()
    assert out, "Empty CLI response"
    payload = json.loads(out.splitlines()[-1])
    mic_input = payload.get("mic_input", {})
    return dict(mic_input)


async def _set_mic_input_gains(
    sess: RemoteAudioSession,
    sat1_cmd: str,
    *,
    mic_gain: int | None = None,
    ref_gain: int | None = None,
) -> None:
    t0 = time.monotonic()
    mic_input: dict[str, object] = {}
    if mic_gain is not None:
        mic_input["mic_gain"] = int(mic_gain)
    if ref_gain is not None:
        mic_input["ref_gain"] = int(ref_gain)

    payload = {"mic_input": mic_input}
    payload_json = shlex.quote(json.dumps(payload, separators=(",", ":")))
    cmd = f"set-mic-pipeline-settings --json {payload_json}"
    result: CmdResult = await sess.cmd(
        f"{sat1_cmd} xmos {cmd}", timeout=REMOTE_CLI_TIMEOUT_S
    )

    assert result.exit_status == 0, f"CLI failed: {result.stderr}"

    if _timing_enabled():
        elapsed = time.monotonic() - t0
        mic_str = f"{mic_gain:#x}" if mic_gain is not None else "None"
        ref_str = f"{ref_gain:#x}" if ref_gain is not None else "None"
        desc = f"gain mic={mic_str} ref={ref_str}".ljust(35)
        print(f"[TIMING] set_gains: {desc} -> {elapsed:.3f}s")


async def _set_mic_input_routing(
    sess: RemoteAudioSession,
    sat1_cmd: str,
    *,
    ref_source_mode: int | None = None,
    mic_source_mode: int | None = None,
    ref_input_channel_map: list[int] | None = None,
    mic_input_channel_map: list[int] | None = None,
) -> None:
    t0 = time.monotonic()
    if ref_input_channel_map is None and mic_input_channel_map is None:
        current = await _get_audio_settings(sess, sat1_cmd)
        ref_input_channel_map = (
            list(current.get("ref_input_channel_map", ()))
            if current.get("ref_input_channel_map")
            else None
        )
        mic_input_channel_map = (
            list(current.get("mic_input_channel_map", ()))
            if current.get("mic_input_channel_map")
            else None
        )
    mic_input: dict[str, object] = {}
    if ref_source_mode is not None:
        mic_input["ref_source_mode"] = int(ref_source_mode)
    if mic_source_mode is not None:
        mic_input["mic_source_mode"] = int(mic_source_mode)
    if ref_input_channel_map is not None:
        mic_input["ref_input_channel_map"] = [int(c) for c in ref_input_channel_map]
    if mic_input_channel_map is not None:
        mic_input["mic_input_channel_map"] = [int(c) for c in mic_input_channel_map]

    payload = {"mic_input": mic_input}
    payload_json = shlex.quote(json.dumps(payload, separators=(",", ":")))
    cmd = f"set-mic-pipeline-settings --json {payload_json}"
    result: CmdResult = await sess.cmd(
        f"{sat1_cmd} xmos {cmd}", timeout=REMOTE_CLI_TIMEOUT_S
    )

    assert result.exit_status == 0, f"CLI failed: {result.stderr}"

    if _timing_enabled():
        elapsed = time.monotonic() - t0
        desc = f"routing ref_src={ref_source_mode} mic_src={mic_source_mode}".ljust(35)
        print(f"[TIMING] set_routing: {desc} -> {elapsed:.3f}s")


async def _set_mic_output_channels(
    sess: RemoteAudioSession,
    sat1_cmd: str,
    left: int,
    right: int,
) -> None:
    t0 = time.monotonic()
    payload = {
        "mic_output": {
            "i2s_channel_map": [int(left), int(right)],
        }
    }
    payload_json = shlex.quote(json.dumps(payload, separators=(",", ":")))
    cmd = f"set-mic-pipeline-settings --json {payload_json}"
    result: CmdResult = await sess.cmd(
        f"{sat1_cmd} xmos {cmd}", timeout=REMOTE_CLI_TIMEOUT_S
    )

    assert result.exit_status == 0, f"CLI failed: {result.stderr}"

    if _timing_enabled():
        elapsed = time.monotonic() - t0
        print(f"[TIMING] set_out_ch: left={left} right={right} -> {elapsed:.3f}s")


async def _set_mic_output_packing(
    sess: RemoteAudioSession,
    sat1_cmd: str,
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
    payload_json = shlex.quote(json.dumps(payload, separators=(",", ":")))
    cmd = f"set-mic-pipeline-settings --json {payload_json}"
    result: CmdResult = await sess.cmd(
        f"{sat1_cmd} xmos {cmd}", timeout=REMOTE_CLI_TIMEOUT_S
    )
    assert result.exit_status == 0, f"CLI failed: {result.stderr}"
    if _timing_enabled():
        elapsed = time.monotonic() - t0
        print(f"[TIMING] set_packing: enabled={enabled} -> {elapsed:.3f}s")


async def _set_mic_output_ref_overwrite(
    sess: RemoteAudioSession,
    sat1_cmd: str,
    *,
    enabled: bool,
) -> None:
    payload = {"mic_output": {"overwrite_ref_with_ic_ns_output": int(bool(enabled))}}
    payload_json = shlex.quote(json.dumps(payload, separators=(",", ":")))
    cmd = f"set-mic-pipeline-settings --json {payload_json}"
    result: CmdResult = await sess.cmd(
        f"{sat1_cmd} xmos {cmd}", timeout=REMOTE_CLI_TIMEOUT_S
    )
    assert result.exit_status == 0, f"CLI failed: {result.stderr}"


async def _capture_rms_fullband(
    sess: RemoteAudioSession,
    *,
    duration_s: float = 1.0,
    channel_index: int = 0,
) -> tuple[float, int]:
    """Capture audio and return (RMS, peak)."""
    t0 = time.monotonic()

    if sess.is_running:
        await sess.stop()

    remote_path = f"/tmp/rec_{int(time.time() * 1000)}.wav"
    await sess.start_record(
        remote_path=remote_path,
        num_channels=2,
        rate_hz=I2S_RATE_HZ,
        fmt="S32_LE",
        arecord_args=[
            f"-D{SAT1_HIL_ARECORD_DEV}",
            f"-d{max(1, int(math.ceil(duration_s)))}",
        ],
    )

    await asyncio.sleep(duration_s)
    await sess.stop()

    local_tmp = Path(f"/tmp/rec_{int(time.time() * 1000)}.wav")
    await sess.download(local_tmp, remote_path=remote_path)

    with open(local_tmp, "rb") as f:
        wav_data = f.read()
    local_tmp.unlink(missing_ok=True)

    samples = _extract_samples_from_wav(wav_data, channel_index=channel_index)
    rms_val = _rms(samples)
    peak = max(abs(v) for v in samples)

    await sess.cmd(f"rm -f {remote_path}", check=False)

    if _timing_enabled():
        elapsed = time.monotonic() - t0
        print(
            f"[TIMING] arecord: {duration_s:.1f}s cap -> {elapsed:.3f}s ({len(samples)} samples)"
        )

    return rms_val, peak


async def _capture_rms_median_fullband(
    sess: RemoteAudioSession,
    *,
    repeats: int,
    duration_s: float,
    channel_index: int = 0,
) -> tuple[float, int]:
    """Capture multiple times and return median RMS with max peak."""
    rms_values: list[float] = []
    peak = 0
    for _ in range(repeats):
        rms, capture_peak = await _capture_rms_fullband(
            sess,
            duration_s=duration_s,
            channel_index=channel_index,
        )
        rms_values.append(rms)
        peak = max(peak, capture_peak)
    return statistics.median(rms_values), peak


async def _record_play_and_download(
    sess: RemoteAudioSession,
    rec_sess: RemoteAudioSession,
    *,
    remote_wav: str,
    duration_s: float,
    local_dir: Path,
) -> Path:
    remote_recorded_path = f"/tmp/rec_{int(time.time() * 1000)}.wav"
    duration_int = max(1, int(math.ceil(duration_s)))

    if sess.is_running:
        await sess.stop()
    if rec_sess.is_running:
        await rec_sess.stop()

    await rec_sess.start_record(
        remote_path=remote_recorded_path,
        num_channels=2,
        rate_hz=I2S_RATE_HZ,
        fmt="S32_LE",
        arecord_args=[
            f"-D{SAT1_HIL_ARECORD_DEV}",
            f"-d{duration_int}",
        ],
    )
    await sess.start_play(
        remote_path=remote_wav,
        num_channels=2,
        aplay_args=[f"-D{SAT1_HIL_APLAY_DEV}"],
    )
    await asyncio.sleep(duration_s)

    if sess.is_running:
        await sess.stop()
    if rec_sess.is_running:
        await rec_sess.stop()

    local_path = local_dir / Path(remote_recorded_path).name
    await rec_sess.download(local_path, remote_path=remote_recorded_path)
    await rec_sess.cmd(f"rm -f {remote_recorded_path}", check=False)
    return local_path


async def _wait_for_signal(
    sess: RemoteAudioSession,
    min_rms: float = MIC_GAIN_SIGNAL_MIN_RMS,
    timeout_s: float = MIC_GAIN_SIGNAL_WAIT_TIMEOUT_S,
    check_duration_s: float = MIC_GAIN_SIGNAL_CHECK_DURATION_S,
) -> float:
    """Wait until captured signal exceeds minimum RMS threshold."""
    t0 = time.monotonic()
    attempts = 0
    while time.monotonic() - t0 < timeout_s:
        attempts += 1
        rms, _ = await _capture_rms_fullband(sess, duration_s=check_duration_s)
        if rms >= min_rms:
            elapsed = time.monotonic() - t0
            if _timing_enabled():
                print(
                    f"[TIMING] wait_signal: {attempts} attempts -> {elapsed:.3f}s (RMS={rms:.1f})"
                )
            return rms
        await asyncio.sleep(0.02)

    elapsed = time.monotonic() - t0
    raise RuntimeError(
        f"No signal detected (RMS<{min_rms}) within {timeout_s}s "
        f"(waited {elapsed:.2f}s, {attempts} attempts)"
    )


@pytest.fixture
async def audio_settings_guard(
    require_hil: None,
    hil_rpi_host: str,
    hil_cli_cmd: str,
):
    """Async fixture that saves and restores audio settings."""
    sess = cast(RemoteAudioSession, await RemoteAudioSession.connect(hil_rpi_host))
    original = await _get_audio_settings(sess, hil_cli_cmd)
    try:
        yield (sess, original)
    finally:
        if original.get("mic_gain") is not None or original.get("ref_gain") is not None:
            await _set_mic_input_gains(
                sess,
                hil_cli_cmd,
                mic_gain=original.get("mic_gain"),
                ref_gain=original.get("ref_gain"),
            )
        await _set_mic_input_routing(
            sess,
            hil_cli_cmd,
            ref_source_mode=original.get("ref_source_mode"),
            mic_source_mode=original.get("mic_source_mode"),
            ref_input_channel_map=list(original.get("ref_input_channel_map", ()))
            if original.get("ref_input_channel_map")
            else None,
            mic_input_channel_map=list(original.get("mic_input_channel_map", ()))
            if original.get("mic_input_channel_map")
            else None,
        )
        await sess.close()


@pytest.mark.hil
async def test_hil_mic_input_settings_shape(
    audio_settings_guard: tuple,
) -> None:
    """Test that audio settings have expected shape."""
    _, settings = audio_settings_guard
    assert "mic_gain" in settings
    assert "ref_gain" in settings
    assert len(settings["ref_input_channel_map"]) == 2
    assert len(settings["mic_input_channel_map"]) >= 2


@pytest.mark.hil
async def test_hil_mic_input_gain_roundtrip(
    audio_settings_guard: tuple,
    hil_rpi_host: str,
    hil_cli_cmd: str,
) -> None:
    """Test that mic gain settings round-trip correctly."""
    sess, _ = audio_settings_guard

    await _set_mic_input_gains(
        sess,
        hil_cli_cmd,
        mic_gain=0x18000000,
        ref_gain=0x10000000,
    )

    current = await _get_audio_settings(sess, hil_cli_cmd)
    assert current["mic_gain"] == 0x18000000
    assert current["ref_gain"] == 0x10000000


@pytest.mark.hil
@pytest.mark.parametrize(
    ("mic_left", "mic_right", "mic_gain"),
    [(0, 1, Q30_LOW), (2, 3, MIC_GAIN_TEST_HIGH)],
    ids=("mic_0_1_low", "mic_2_3_high"),
)
async def test_hil_mic_gain_changes_captured_level(
    audio_settings_guard: tuple,
    tmp_path: Path,
    hil_rpi_host: str,
    hil_cli_cmd: str,
    mic_left: int,
    mic_right: int,
    mic_gain: int,
) -> None:
    """Test that changing mic gain affects captured signal level."""
    total_t0 = time.monotonic()
    step_t0 = total_t0

    def _step_timing(label: str) -> None:
        nonlocal step_t0
        if _timing_enabled():
            elapsed = time.monotonic() - step_t0
            print(f"[TIMING] {label} -> {elapsed:.3f}s")
        step_t0 = time.monotonic()

    async def _ensure_playing(remote_path: str) -> None:
        if sess.is_running:
            return
        t0 = time.monotonic()
        await sess.start_play(
            remote_path=remote_path,
            num_channels=2,
            aplay_args=[f"-D{SAT1_HIL_APLAY_DEV}"],
        )
        if _timing_enabled():
            elapsed = time.monotonic() - t0
            print(f"[TIMING] start_play(restart) -> {elapsed:.3f}s")

    sess, _ = audio_settings_guard
    rec_sess = cast(RemoteAudioSession, await RemoteAudioSession.connect(hil_rpi_host))
    left_output_ch = MIC_OUTPUT_BASE_CH + mic_left
    right_output_ch = MIC_OUTPUT_BASE_CH + mic_right
    mic_map = _packaged_input_map_for_board()

    if MIC_GAIN_FIXTURE_USE_DEDICATED:
        local_wav = MIC_GAIN_FIXTURE_WAV
        if not local_wav.exists():
            raise FileNotFoundError(
                f"Dedicated mic-gain fixture not found: {local_wav}. "
                "Generate it with: python3 tools/e2e/generate_mic_gain_fixture.py "
                "--output tests/test_hil/fixtures/mic_gain_test_fixture.wav"
            )
    else:
        local_wav = fixture_wav_required(MIC_GAIN_FIXTURE_ANGLE_DEG)

    await _set_mic_output_packing(
        sess,
        hil_cli_cmd,
        enabled=False,
    )
    _step_timing("set_output_packing")
    await _set_mic_output_channels(
        sess,
        hil_cli_cmd,
        left_output_ch,
        right_output_ch,
    )
    _step_timing("set_output_channels")

    await _set_mic_input_routing(
        sess,
        hil_cli_cmd,
        ref_source_mode=REF_SOURCE_DOWNSAMPLED,
        mic_source_mode=MIC_SOURCE_PACKAGED_INPUT,
    )
    _step_timing("set_input_routing_modes")

    t0 = time.monotonic()
    remote_wav = f"/tmp/sat1_mic_gain_fixture_{int(time.time())}.wav"
    await sess.upload(local_wav, remote_path=remote_wav)
    elapsed = time.monotonic() - t0
    if _timing_enabled():
        print(f"[TIMING] upload: {local_wav.name} -> remote -> {elapsed:.3f}s")
    _step_timing("upload_fixture")

    t0 = time.monotonic()
    await sess.start_play(
        remote_path=remote_wav,
        num_channels=2,
        aplay_args=[f"-D{SAT1_HIL_APLAY_DEV}"],
    )
    elapsed = time.monotonic() - t0
    if _timing_enabled():
        print(f"[TIMING] start_play: ssh+aplay spawn -> {elapsed:.3f}s")
    _step_timing("start_play")

    try:
        await asyncio.sleep(MIC_GAIN_DECODER_SYNC_WAIT_S)
        _step_timing("decoder_sync_wait")

        await _ensure_playing(remote_wav)
        probe_rms = await _wait_for_signal(rec_sess)
        _step_timing("wait_for_signal_probe")
        print(
            f"Signal detected: RMS={probe_rms:.1f} (mic_left={mic_left}, mic_right={mic_right})"
        )

        await _set_mic_input_gains(
            sess,
            hil_cli_cmd,
            mic_gain=mic_gain,
            ref_gain=Q30_UNITY,
        )
        _step_timing("set_gains")
        await _set_mic_input_routing(
            sess,
            hil_cli_cmd,
            mic_input_channel_map=mic_map,
        )
        _step_timing("set_input_map")
        await asyncio.sleep(MIC_GAIN_WARMUP_SEC)
        _step_timing("warmup")

        await _ensure_playing(remote_wav)
        await _wait_for_signal(rec_sess)
        _step_timing("wait_for_signal")

        run_dir = tmp_path / f"mic_gain_{mic_left}_{mic_right}_{int(time.time())}"
        run_dir.mkdir(parents=True, exist_ok=True)
        local_recorded_path = await _record_play_and_download(
            sess,
            rec_sess,
            remote_wav=remote_wav,
            duration_s=float(MIC_GAIN_RECORD_SECONDS),
            local_dir=run_dir,
        )
        _step_timing("capture_recording")
        left = _estimate_gain_from_recording(
            injected_path=local_wav,
            recorded_path=local_recorded_path,
            packed_lane=int(mic_map[mic_left]),
            recorded_channel=0,
        )
        right = _estimate_gain_from_recording(
            injected_path=local_wav,
            recorded_path=local_recorded_path,
            packed_lane=int(mic_map[mic_right]),
            recorded_channel=1,
        )

    finally:
        if sess.is_running:
            await sess.stop()
        await sess.cmd(f"rm -f {remote_wav}", check=False)
        if rec_sess.is_running:
            await rec_sess.stop()
        await rec_sess.close()
        if _timing_enabled():
            total_elapsed = time.monotonic() - total_t0
            print(f"[TIMING] test_total -> {total_elapsed:.3f}s")
    for label, mic_idx, measure in (
        ("left", mic_left, left),
        ("right", mic_right, right),
    ):
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
async def test_hil_ref_gain_changes_captured_level(
    audio_settings_guard: tuple,
    tmp_path: Path,
    hil_rpi_host: str,
    hil_cli_cmd: str,
) -> None:
    local_wav = MIC_GAIN_FIXTURE_WAV
    if not local_wav.exists():
        raise FileNotFoundError(
            f"Dedicated mic-gain fixture not found: {local_wav}. "
            "Generate it with: python3 tools/e2e/generate_mic_gain_fixture.py "
            "--output tests/test_hil/fixtures/mic_gain_test_fixture.wav"
        )
    local_wav = Path(local_wav)

    sess, _ = audio_settings_guard
    rec_sess = cast(RemoteAudioSession, await RemoteAudioSession.connect(hil_rpi_host))
    remote_wav = f"/tmp/sat1_ref_gain_fixture_{int(time.time())}.wav"

    await sess.upload(local_wav, remote_path=remote_wav)

    try:
        await _set_mic_output_ref_overwrite(
            sess,
            hil_cli_cmd,
            enabled=False,
        )
        await _set_mic_output_packing(
            sess,
            hil_cli_cmd,
            enabled=False,
        )
        await _set_mic_output_channels(
            sess,
            hil_cli_cmd,
            REF_OUTPUT_CH_MAP[0],
            REF_OUTPUT_CH_MAP[1],
        )
        await _set_mic_input_gains(
            sess,
            hil_cli_cmd,
            mic_gain=Q30_UNITY,
            ref_gain=Q30_LOW,
        )
        await _set_mic_input_routing(
            sess,
            hil_cli_cmd,
            ref_source_mode=REF_SOURCE_DOWNSAMPLED,
            mic_source_mode=MIC_SOURCE_PACKAGED_INPUT,
            mic_input_channel_map=_packaged_input_map_for_board(),
        )

        low_dir = tmp_path / f"ref_gain_low_{int(time.time())}"
        low_dir.mkdir(parents=True, exist_ok=True)
        low_path = await _record_play_and_download(
            sess,
            rec_sess,
            remote_wav=remote_wav,
            duration_s=float(MIC_GAIN_RECORD_SECONDS),
            local_dir=low_dir,
        )
        low_left = _estimate_recorded_level(
            recorded_path=low_path,
            recorded_channel=0,
        )
        low_right = _estimate_recorded_level(
            recorded_path=low_path,
            recorded_channel=1,
        )

        await _set_mic_input_gains(
            sess,
            hil_cli_cmd,
            mic_gain=Q30_UNITY,
            ref_gain=Q30_UNITY,
        )

        high_dir = tmp_path / f"ref_gain_high_{int(time.time())}"
        high_dir.mkdir(parents=True, exist_ok=True)
        high_path = await _record_play_and_download(
            sess,
            rec_sess,
            remote_wav=remote_wav,
            duration_s=float(MIC_GAIN_RECORD_SECONDS),
            local_dir=high_dir,
        )
        high_left = _estimate_recorded_level(
            recorded_path=high_path,
            recorded_channel=0,
        )
        high_right = _estimate_recorded_level(
            recorded_path=high_path,
            recorded_channel=1,
        )
    finally:
        if sess.is_running:
            await sess.stop()
        await sess.cmd(f"rm -f {remote_wav}", check=False)
        if rec_sess.is_running:
            await rec_sess.stop()
        await rec_sess.close()

    expected_ratio = float(Q30_UNITY) / float(Q30_LOW)
    for label, low, high in (
        ("left", low_left, high_left),
        ("right", low_right, high_right),
    ):
        low_level = float(low["recorded_active_p50"])
        high_level = float(high["recorded_active_p50"])
        low_peak = int(low["recorded_peak"])
        high_peak = int(high["recorded_peak"])
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
