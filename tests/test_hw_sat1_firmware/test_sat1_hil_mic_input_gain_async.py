"""
Async SAT1 HIL mic input gain tests using persistent SSH connections.

This module provides async versions of the mic gain tests that use
hil_utils.RemoteAudioSession for efficient audio playback/recording
over a single persistent SSH connection.
"""

import asyncio
import math
import os
import re
import statistics
import struct
import time
from pathlib import Path
from typing import cast

import pytest

from hil_utils import RemoteAudioSession, CmdResult
from tests.conftest import PROJ_ROOT
from tests.test_doa.conftest import fixture_wav_required


# Constants
Q30_UNITY = 0x40000000
Q30_LOW = 0x08000000
REF_SOURCE_LEGACY_DOWNSAMPLED = 0
MIC_SOURCE_PACKAGED_INPUT = 1
MIC_OUTPUT_BASE_CH = 4
PACKAGED_INPUT_FULL_MAP = [0, 1, 2, 3]
UPSAMPLE_CHANNEL_MAP_DEFAULT = [0, 1, 2, 3, 4, 5]

# Configurable via environment
MIC_GAIN_CAPTURE_REPEATS = int(os.getenv("SAT1_HIL_MIC_GAIN_CAPTURE_REPEATS", "3"))
MIC_GAIN_CAPTURE_SEC = int(os.getenv("SAT1_HIL_MIC_GAIN_CAPTURE_SEC", "1"))
MIC_GAIN_WARMUP_SEC = float(os.getenv("SAT1_HIL_MIC_GAIN_WARMUP_SEC", "0.4"))
MIC_GAIN_MIN_RATIO = float(os.getenv("SAT1_HIL_MIC_GAIN_MIN_RATIO", "1.05"))
MIC_GAIN_MAX_PEAK = int(os.getenv("SAT1_HIL_MIC_GAIN_MAX_PEAK", str(0x70000000)))
MIC_GAIN_TEST_HIGH = int(os.getenv("SAT1_HIL_MIC_GAIN_TEST_HIGH", str(0x20000000)))
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
I2S_RATE_HZ = 48000
PIPELINE_RATE_HZ = 16000
UPSAMPLE_FACTOR = I2S_RATE_HZ // PIPELINE_RATE_HZ
REMOTE_CLI_TIMEOUT_S = int(os.getenv("SAT1_HIL_REMOTE_SDK_TIMEOUT_S", "40"))


def _timing_enabled() -> bool:
    return bool(os.getenv("SAT1_HIL_TIMING", ""))


def _rms(samples: list[int]) -> float:
    """Calculate RMS of sample list."""
    assert samples, "Expected non-empty sample list"
    acc = 0
    for s in samples:
        acc += s * s
    return math.sqrt(acc / len(samples))


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


def _parse_cli_repr(out: str) -> dict:
    match = re.match(r"(\w+)\((.*)\)$", out)
    if not match:
        raise ValueError(f"Unexpected CLI output format: {out}")

    fields_str = match.group(2)
    result_dict: dict[str, object] = {}

    def _parse_value(val_str: str) -> object:
        val_str = val_str.strip()
        if val_str.startswith("(") and val_str.endswith(")"):
            inner = val_str[1:-1]
            return tuple(int(x.strip()) for x in inner.split(",") if x.strip())
        try:
            return int(val_str)
        except ValueError:
            return val_str

    depth = 0
    current_field = ""
    current_value = ""
    in_value = False

    for ch in fields_str:
        if not in_value:
            if ch == "=":
                in_value = True
            elif ch.isalnum() or ch == "_":
                current_field += ch
        else:
            if ch == "(":
                depth += 1
                current_value += ch
            elif ch == ")":
                depth -= 1
                current_value += ch
            elif ch == "," and depth == 0:
                result_dict[current_field] = _parse_value(current_value)
                current_field = ""
                current_value = ""
                in_value = False
            else:
                current_value += ch

    if current_field:
        result_dict[current_field] = _parse_value(current_value)

    return result_dict


async def _run_cli_command(
    sess: RemoteAudioSession,
    sat1_cmd: str,
    cmd: str,
) -> dict:
    """Run a CLI command and parse repr response."""
    t0 = time.monotonic()
    full_cmd = f"{sat1_cmd} xmos {cmd}"
    result: CmdResult = await sess.cmd(full_cmd, timeout=REMOTE_CLI_TIMEOUT_S)

    if _timing_enabled():
        elapsed = time.monotonic() - t0
        print(f"[TIMING] cli: {cmd[:40]:<40} -> {elapsed:.3f}s")

    assert result.exit_status == 0, f"CLI failed: {result.stderr}"
    out = result.stdout if isinstance(result.stdout, str) else result.stdout.decode()
    out = out.strip()
    assert out, "Empty CLI response"
    return _parse_cli_repr(out)


async def _get_audio_settings(sess: RemoteAudioSession, sat1_cmd: str) -> dict:
    return await _run_cli_command(sess, sat1_cmd, "get-mic-input-settings")


async def _set_mic_input_gains(
    sess: RemoteAudioSession,
    sat1_cmd: str,
    *,
    mic_gain: int | None = None,
    ref_gain: int | None = None,
) -> None:
    t0 = time.monotonic()
    args = []
    if mic_gain is not None:
        args.extend(["--mic-gain", str(mic_gain)])
    if ref_gain is not None:
        args.extend(["--ref-gain", str(ref_gain)])

    cmd = "set-mic-input-gains" + (" " + " ".join(args) if args else "")
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
    args = []
    if ref_source_mode is not None:
        args.extend(["--ref-source-mode", str(ref_source_mode)])
    if mic_source_mode is not None:
        args.extend(["--mic-source-mode", str(mic_source_mode)])
    if ref_input_channel_map is not None:
        args.extend(
            ["--ref-input-channel-map"] + [str(c) for c in ref_input_channel_map]
        )
    if mic_input_channel_map is not None:
        args.extend(
            ["--mic-input-channel-map"] + [str(c) for c in mic_input_channel_map]
        )

    cmd = "set-mic-input-routing" + (" " + " ".join(args) if args else "")
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
    cmd = f"set-mic-output {left} {right}"
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
    """No-op: CLI does not expose packing controls."""
    if _timing_enabled():
        print(f"[TIMING] set_packing: enabled={enabled} -> SKIPPED (not in CLI)")


async def _capture_rms_fullband(
    sess: RemoteAudioSession,
    *,
    duration_s: float = 1.0,
) -> tuple[float, int]:
    """Capture audio and return (RMS, peak)."""
    t0 = time.monotonic()

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

    samples = _extract_samples_from_wav(wav_data, channel_index=0)
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
) -> tuple[float, int]:
    """Capture multiple times and return median RMS with max peak."""
    rms_values: list[float] = []
    peak = 0
    for _ in range(repeats):
        rms, capture_peak = await _capture_rms_fullband(
            sess,
            duration_s=duration_s,
        )
        rms_values.append(rms)
        peak = max(peak, capture_peak)
    return statistics.median(rms_values), peak


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
def require_sat1_hil():
    """Require SAT1_HIL environment variable for HIL tests."""
    assert os.getenv("SAT1_HIL"), "SAT1_HIL=1 required for hardware-in-the-loop tests"


@pytest.fixture
def sat1_rpi_host() -> str:
    """Get SAT1 RPi host from environment."""
    host = os.getenv("SAT1_RPI_HOST")
    assert host, "SAT1_RPI_HOST required for SAT1 HIL tests"
    return host


@pytest.fixture
def sat1_rpi_sat1_cmd() -> str:
    """Get SAT1 CLI command from environment."""
    return os.getenv("SAT1_RPI_CLI_CMD", "sat1")


@pytest.fixture
async def audio_settings_guard(
    require_sat1_hil: None,
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
):
    """Async fixture that saves and restores audio settings."""
    sess = cast(RemoteAudioSession, await RemoteAudioSession.connect(sat1_rpi_host))
    original = await _get_audio_settings(sess, sat1_rpi_sat1_cmd)
    try:
        yield (sess, original)
    finally:
        if original.get("mic_gain") is not None or original.get("ref_gain") is not None:
            await _set_mic_input_gains(
                sess,
                sat1_rpi_sat1_cmd,
                mic_gain=original.get("mic_gain"),
                ref_gain=original.get("ref_gain"),
            )
        await _set_mic_input_routing(
            sess,
            sat1_rpi_sat1_cmd,
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
@pytest.mark.sat1
async def test_mic_input_settings_shape_sat1(
    audio_settings_guard: tuple,
) -> None:
    """Test that audio settings have expected shape."""
    _, settings = audio_settings_guard
    assert "mic_gain" in settings
    assert "ref_gain" in settings
    assert len(settings["ref_input_channel_map"]) == 2
    assert len(settings["mic_input_channel_map"]) >= 2


@pytest.mark.hil
@pytest.mark.sat1
async def test_mic_input_gain_roundtrip_sat1(
    audio_settings_guard: tuple,
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
) -> None:
    """Test that mic gain settings round-trip correctly."""
    sess, _ = audio_settings_guard

    await _set_mic_input_gains(
        sess,
        sat1_rpi_sat1_cmd,
        mic_gain=0x18000000,
        ref_gain=0x10000000,
    )

    current = await _get_audio_settings(sess, sat1_rpi_sat1_cmd)
    assert current["mic_gain"] == 0x18000000
    assert current["ref_gain"] == 0x10000000


@pytest.mark.hil
@pytest.mark.sat1
@pytest.mark.parametrize("mic_idx", [0, 1, 2, 3])
async def test_mic_gain_changes_captured_level_sat1(
    audio_settings_guard: tuple,
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
    mic_idx: int,
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
    rec_sess = cast(RemoteAudioSession, await RemoteAudioSession.connect(sat1_rpi_host))
    target_output_ch = MIC_OUTPUT_BASE_CH + mic_idx
    mic_map = list(PACKAGED_INPUT_FULL_MAP)

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
                "Generate it with: python3 tools/doa/generate_mic_gain_fixture.py "
                "--output tests/test_doa/fixtures/lag_synth/mic_gain_test_fixture.wav"
            )
    else:
        local_wav = fixture_wav_required(MIC_GAIN_FIXTURE_ANGLE_DEG)

    await _set_mic_output_packing(
        sess,
        sat1_rpi_sat1_cmd,
        enabled=True,
        upsample_channel_map=UPSAMPLE_CHANNEL_MAP_DEFAULT,
    )
    _step_timing("set_output_packing")
    await _set_mic_output_channels(
        sess,
        sat1_rpi_sat1_cmd,
        target_output_ch,
        target_output_ch,
    )
    _step_timing("set_output_channels")

    await _set_mic_input_routing(
        sess,
        sat1_rpi_sat1_cmd,
        ref_source_mode=REF_SOURCE_LEGACY_DOWNSAMPLED,
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
        print(f"Signal detected: RMS={probe_rms:.1f} (mic_idx={mic_idx})")

        await _set_mic_input_gains(
            sess,
            sat1_rpi_sat1_cmd,
            mic_gain=Q30_LOW,
            ref_gain=Q30_UNITY,
        )
        _step_timing("set_gains_low")
        await _set_mic_input_routing(
            sess,
            sat1_rpi_sat1_cmd,
            mic_input_channel_map=mic_map,
        )
        _step_timing("set_input_map_low")
        await asyncio.sleep(MIC_GAIN_WARMUP_SEC)
        _step_timing("warmup_low")

        await _ensure_playing(remote_wav)
        await _wait_for_signal(rec_sess)
        _step_timing("wait_for_signal_low")

        await _ensure_playing(remote_wav)
        low_rms, low_peak = await _capture_rms_median_fullband(
            rec_sess,
            repeats=MIC_GAIN_CAPTURE_REPEATS,
            duration_s=float(MIC_GAIN_CAPTURE_SEC),
        )
        _step_timing("capture_low")
        print(f"LOW gain: RMS={low_rms:.1f}, peak={low_peak} (mic_idx={mic_idx})")

        await _set_mic_input_gains(
            sess,
            sat1_rpi_sat1_cmd,
            mic_gain=MIC_GAIN_TEST_HIGH,
            ref_gain=Q30_UNITY,
        )
        _step_timing("set_gains_high")
        await _set_mic_input_routing(
            sess,
            sat1_rpi_sat1_cmd,
            mic_input_channel_map=mic_map,
        )
        _step_timing("set_input_map_high")
        await asyncio.sleep(MIC_GAIN_WARMUP_SEC)
        _step_timing("warmup_high")

        await _ensure_playing(remote_wav)
        await _wait_for_signal(rec_sess)
        _step_timing("wait_for_signal_high")

        await _ensure_playing(remote_wav)
        high_rms, high_peak = await _capture_rms_median_fullband(
            rec_sess,
            repeats=MIC_GAIN_CAPTURE_REPEATS,
            duration_s=float(MIC_GAIN_CAPTURE_SEC),
        )
        _step_timing("capture_high")
        print(f"HIGH gain: RMS={high_rms:.1f}, peak={high_peak} (mic_idx={mic_idx})")

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

    assert low_rms >= 1.0 and high_rms >= 1.0, (
        "Insufficient mic signal for gain validation "
        f"(mic_idx={mic_idx}, low={low_rms:.2f}, high={high_rms:.2f})"
    )

    assert low_peak < MIC_GAIN_MAX_PEAK, (
        f"Low-gain capture clipped (mic_idx={mic_idx}, peak={low_peak})"
    )
    assert high_peak < MIC_GAIN_MAX_PEAK, (
        f"High-gain capture clipped (mic_idx={mic_idx}, peak={high_peak})"
    )

    ratio = high_rms / low_rms
    assert ratio > MIC_GAIN_MIN_RATIO, (
        f"Expected mic gain to increase captured RMS "
        f"(mic_idx={mic_idx}, low={low_rms:.2f}, high={high_rms:.2f}, "
        f"ratio={ratio:.3f}, min_ratio={MIC_GAIN_MIN_RATIO:.3f})"
    )
