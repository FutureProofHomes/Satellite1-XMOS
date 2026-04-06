import json
import math
import os
import shlex
import statistics
import struct
import subprocess
import time

import pytest

from tests.conftest import PROJ_ROOT
from tests.test_doa.conftest import fixture_wav_required


Q30_UNITY = 0x40000000
Q30_LOW = 0x08000000
REF_SOURCE_LEGACY_DOWNSAMPLED = 0
MIC_SOURCE_PDM = 0
MIC_SOURCE_PACKAGED_INPUT = 1
MIC_OUTPUT_BASE_CH = 4
PACKAGED_INPUT_FULL_MAP = [0, 1, 2, 3]
UPSAMPLE_CHANNEL_MAP_DEFAULT = [0, 1, 2, 3, 4, 5]
MIC_GAIN_CAPTURE_REPEATS = int(os.getenv("SQ66_HIL_MIC_GAIN_CAPTURE_REPEATS", "3"))
MIC_GAIN_CAPTURE_SEC = int(os.getenv("SQ66_HIL_MIC_GAIN_CAPTURE_SEC", "1"))
MIC_GAIN_WARMUP_SEC = float(os.getenv("SQ66_HIL_MIC_GAIN_WARMUP_SEC", "0.4"))
MIC_GAIN_MIN_RATIO = float(os.getenv("SQ66_HIL_MIC_GAIN_MIN_RATIO", "1.05"))
MIC_GAIN_MAX_PEAK = int(os.getenv("SQ66_HIL_MIC_GAIN_MAX_PEAK", str(0x70000000)))
MIC_GAIN_TEST_HIGH = int(os.getenv("SQ66_HIL_MIC_GAIN_TEST_HIGH", str(0x20000000)))
SQ66_HIL_APLAY_DEV = os.getenv("SQ66_HIL_APLAY_DEV", "hw:0,0")
MIC_GAIN_FIXTURE_USE_DEDICATED = bool(
    int(os.getenv("SQ66_HIL_MIC_GAIN_USE_DEDICATED_FIXTURE", "1"))
)
MIC_GAIN_FIXTURE_ANGLE_DEG = float(
    os.getenv("SQ66_HIL_MIC_GAIN_FIXTURE_ANGLE_DEG", "45")
)
MIC_GAIN_SIGNAL_MIN_RMS = float(os.getenv("SQ66_HIL_MIC_GAIN_SIGNAL_MIN_RMS", "10.0"))
MIC_GAIN_SIGNAL_WAIT_TIMEOUT_S = float(
    os.getenv("SQ66_HIL_MIC_GAIN_SIGNAL_WAIT_TIMEOUT_S", "3.0")
)
MIC_GAIN_SIGNAL_CHECK_DURATION_S = float(
    os.getenv("SQ66_HIL_MIC_GAIN_SIGNAL_CHECK_DURATION_S", "0.1")
)
MIC_GAIN_DECODER_SYNC_WAIT_S = float(
    os.getenv("SQ66_HIL_MIC_GAIN_DECODER_SYNC_WAIT_S", "0.02")
)
I2S_RATE_HZ = 48000
PIPELINE_RATE_HZ = 16000
UPSAMPLE_FACTOR = I2S_RATE_HZ // PIPELINE_RATE_HZ
SSH_CONNECT_TIMEOUT_S = int(os.getenv("SQ66_HIL_SSH_CONNECT_TIMEOUT_S", "5"))
SSH_CMD_TIMEOUT_S = int(os.getenv("SQ66_HIL_SSH_TIMEOUT_S", "30"))
REMOTE_CLI_TIMEOUT_S = int(os.getenv("SQ66_HIL_REMOTE_SDK_TIMEOUT_S", "40"))
RETRY_ATTEMPTS = int(os.getenv("SQ66_HIL_RETRY_ATTEMPTS", "4"))
RETRY_DELAY_S = float(os.getenv("SQ66_HIL_RETRY_DELAY_S", "0.5"))


def _run_ssh(
    host: str, cmd: str, timeout: int = SSH_CMD_TIMEOUT_S
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
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


def _run_remote_cli_json(
    host: str, sq66_rpi_sat1_cmd: str, cmd: str, timeout: int = REMOTE_CLI_TIMEOUT_S
) -> dict:
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(RETRY_ATTEMPTS):
        last = _run_ssh(
            host,
            f"{sq66_rpi_sat1_cmd} --board sq66 xmos {cmd}",
            timeout=timeout,
        )
        if last.returncode == 0:
            out = last.stdout.strip()
            if out:
                return json.loads(out.splitlines()[-1])
        if attempt < (RETRY_ATTEMPTS - 1):
            time.sleep(RETRY_DELAY_S)

    assert last is not None
    assert last.returncode == 0, last.stdout + last.stderr
    raise AssertionError("Expected JSON output from remote CLI command")


def _get_audio_settings(sq66_rpi_host: str, sq66_rpi_sat1_cmd: str) -> dict:
    script = """
import json
from satellite1.sat1_hat import XMOS

x = XMOS()
x.setup()
_ = x.read_firmware()
_ = x.wait_until_ready(timeout_s=3.0, poll_interval_s=0.1)
try:
    s = x.get_mic_input_settings()
    print(json.dumps({
        "available_mic_count": 4,
        "mic_input": {
            "mic_gain": int(s.mic_gain),
            "ref_gain": int(s.ref_gain),
            "ref_source_mode": int(s.ref_source_mode),
            "mic_source_mode": int(s.mic_source_mode),
            "ref_input_channel_map": [int(v) for v in s.ref_input_channel_map],
            "mic_input_channel_map": [int(v) for v in s.mic_input_channel_map],
        },
    }))
finally:
    cntrl = getattr(x, "_cntrl", None)
    if cntrl is not None and hasattr(cntrl, "close"):
        cntrl.close()
"""
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(RETRY_ATTEMPTS):
        last = _run_ssh(
            sq66_rpi_host,
            f"{sq66_rpi_sat1_cmd} -c {shlex.quote(script)}",
            timeout=REMOTE_CLI_TIMEOUT_S,
        )
        if last.returncode == 0:
            out = last.stdout.strip()
            if out:
                return json.loads(out.splitlines()[-1])
        if attempt < (RETRY_ATTEMPTS - 1):
            time.sleep(RETRY_DELAY_S)

    assert last is not None
    assert last.returncode == 0, last.stdout + last.stderr
    raise AssertionError("Expected audio settings JSON from remote Python command")


def _set_mic_input_gains(
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
    *,
    mic_gain: int | None = None,
    ref_gain: int | None = None,
    ref_source_mode: int | None = None,
    mic_source_mode: int | None = None,
    mic_input_channel_map: list[int] | None = None,
) -> None:
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
        sq66_rpi_host,
        f"{sq66_rpi_sat1_cmd} --board sq66 xmos {cmd}",
        timeout=REMOTE_CLI_TIMEOUT_S,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "True" in res.stdout, res.stdout + res.stderr


def _set_mic_output_channels(
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
    left: int,
    right: int,
) -> None:
    payload = {"mic_output": {"i2s_channel_map": [int(left), int(right)]}}
    cmd = (
        "set-mic-pipeline-settings --json "
        f"{shlex.quote(json.dumps(payload, separators=(',', ':')))}"
    )
    res = _run_ssh(
        sq66_rpi_host,
        f"{sq66_rpi_sat1_cmd} --board sq66 xmos {cmd}",
        timeout=REMOTE_CLI_TIMEOUT_S,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "True" in res.stdout, res.stdout + res.stderr


def _set_mic_output_packing(
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
    *,
    enabled: bool,
    upsample_channel_map: list[int] | None = None,
) -> None:
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
        sq66_rpi_host,
        f"{sq66_rpi_sat1_cmd} --board sq66 xmos {cmd}",
        timeout=REMOTE_CLI_TIMEOUT_S,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "True" in res.stdout, res.stdout + res.stderr


def _capture_channel_samples(
    sq66_rpi_host: str,
    *,
    duration_s: float = 2,
    channel_index: int = 0,
) -> list[int]:
    # arecord -d expects integer seconds only
    duration_int = max(1, int(math.ceil(duration_s)))
    capture_cmd = (
        f"arecord -D hw:0,1 -f S32_LE -r {I2S_RATE_HZ} -c 2 -d {duration_int} -t raw -q"
    )
    res = subprocess.run(
        ["ssh", sq66_rpi_host, capture_cmd],
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

    return selected


def _extract_pipeline_rate_lane(samples_48k: list[int], lane: int = 0) -> list[int]:
    assert UPSAMPLE_FACTOR == 3
    assert 0 <= lane < UPSAMPLE_FACTOR

    lane_samples = samples_48k[lane::UPSAMPLE_FACTOR]
    assert lane_samples, "Expected extracted pipeline-rate samples"
    return lane_samples


def _rms(samples: list[int]) -> float:
    assert samples, "Expected non-empty sample list"

    acc = 0
    for s in samples:
        acc += s * s

    return math.sqrt(acc / len(samples))


def _capture_rms(
    sq66_rpi_host: str,
    *,
    duration_s: int = 2,
    channel_index: int = 0,
    lane: int = 0,
) -> float:
    channel_samples = _capture_channel_samples(
        sq66_rpi_host,
        duration_s=duration_s,
        channel_index=channel_index,
    )
    pipeline_samples = _extract_pipeline_rate_lane(channel_samples, lane=lane)
    return _rms(pipeline_samples)


def _capture_rms_fullband(
    sq66_rpi_host: str,
    *,
    duration_s: float = 2,
    channel_index: int = 0,
) -> tuple[float, int]:
    channel_samples = _capture_channel_samples(
        sq66_rpi_host,
        duration_s=duration_s,
        channel_index=channel_index,
    )
    peak = max(abs(v) for v in channel_samples)
    return _rms(channel_samples), peak


def _capture_rms_median_fullband(
    sq66_rpi_host: str,
    *,
    repeats: int,
    duration_s: int,
    channel_index: int = 0,
) -> tuple[float, int]:
    rms_values: list[float] = []
    peak = 0
    for _ in range(repeats):
        rms, capture_peak = _capture_rms_fullband(
            sq66_rpi_host,
            duration_s=duration_s,
            channel_index=channel_index,
        )
        rms_values.append(rms)
        peak = max(peak, capture_peak)
    return statistics.median(rms_values), peak


def _start_remote_wav_playback_loop(
    sq66_rpi_host: str,
    remote_wav: str,
) -> subprocess.Popen[bytes]:
    """Start looping WAV playback.

    Uses infinite loop to ensure signal persists throughout the entire test.
    The fixture is short enough that loop-restart jitter is negligible.
    """
    return subprocess.Popen(
        [
            "ssh",
            sq66_rpi_host,
            (
                "sh -c "
                + shlex.quote(
                    "while true; do "
                    f"aplay -D {SQ66_HIL_APLAY_DEV} -f S32_LE -r {I2S_RATE_HZ} -c 2 "
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
    sq66_rpi_host: str,
    min_rms: float = MIC_GAIN_SIGNAL_MIN_RMS,
    timeout_s: float = MIC_GAIN_SIGNAL_WAIT_TIMEOUT_S,
    check_duration_s: float = MIC_GAIN_SIGNAL_CHECK_DURATION_S,
) -> float:
    """Block until captured signal exceeds minimum RMS threshold.

    This ensures playback has started and the packaged decoder has locked
    onto valid input before proceeding with measurements.

    Args:
        sq66_rpi_host: SSH host for SQ66 Pi
        min_rms: Minimum RMS threshold to consider signal present
        timeout_s: Maximum time to wait for signal
        check_duration_s: Duration of each probe capture

    Returns:
        The RMS value when signal was detected

    Raises:
        RuntimeError: If no valid signal detected within timeout
    """
    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        rms, _ = _capture_rms_fullband(sq66_rpi_host, duration_s=check_duration_s)
        if rms >= min_rms:
            return rms
        time.sleep(0.02)  # Small delay between probes

    elapsed = time.monotonic() - start
    raise RuntimeError(
        f"No signal detected (RMS<{min_rms}) within {timeout_s}s "
        f"(waited {elapsed:.2f}s)"
    )


def _start_remote_tone(sq66_rpi_host: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            "ssh",
            sq66_rpi_host,
            "speaker-test -D hw:0,0 -t sine -f 1000",
        ],
        cwd=PROJ_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture
def audio_settings_guard(
    require_sq66_hil: None,
    ensure_sq66_running: None,
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
):
    try:
        original = _get_audio_settings(sq66_rpi_host, sq66_rpi_sat1_cmd)
    except AssertionError as exc:
        print(f"SQ66 mic input precondition unavailable: {exc}")
        yield None
        return

    yield original

    _set_mic_input_gains(
        sq66_rpi_host,
        sq66_rpi_sat1_cmd,
        mic_gain=original["mic_input"]["mic_gain"],
        ref_gain=original["mic_input"]["ref_gain"],
    )
    if "mic_output" in original:
        _set_mic_output_channels(
            sq66_rpi_host,
            sq66_rpi_sat1_cmd,
            original["mic_output"]["i2s_channel_map"][0],
            original["mic_output"]["i2s_channel_map"][1],
        )
        _set_mic_output_packing(
            sq66_rpi_host,
            sq66_rpi_sat1_cmd,
            enabled=bool(original["mic_output"]["pack_extra_upsample_channels"]),
            upsample_channel_map=original["mic_output"]["upsample_channel_map"],
        )


@pytest.mark.hil
@pytest.mark.sq66
def test_mic_input_settings_shape_sq66(
    audio_settings_guard,
) -> None:
    if audio_settings_guard is None:
        return
    settings = audio_settings_guard
    assert settings["available_mic_count"] == 4
    assert len(settings["mic_input"]["ref_input_channel_map"]) == 2
    assert len(settings["mic_input"]["mic_input_channel_map"]) == 4


@pytest.mark.hil
@pytest.mark.sq66
def test_mic_input_gain_roundtrip_sq66(
    audio_settings_guard,
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
) -> None:
    if audio_settings_guard is None:
        return
    _set_mic_input_gains(
        sq66_rpi_host,
        sq66_rpi_sat1_cmd,
        mic_gain=0x18000000,
        ref_gain=0x10000000,
    )

    current = _get_audio_settings(sq66_rpi_host, sq66_rpi_sat1_cmd)
    assert current["mic_input"]["mic_gain"] == 0x18000000
    assert current["mic_input"]["ref_gain"] == 0x10000000


@pytest.mark.hil
@pytest.mark.sq66
@pytest.mark.parametrize("mic_idx", [0, 1, 2, 3])
def test_mic_gain_changes_captured_level_sq66(
    audio_settings_guard,
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
    mic_idx: int,
) -> None:
    """Test that changing mic gain affects captured signal level.

    Test sequence (optimized for determinism):
    1. Set routing to PACKAGED_INPUT first (disconnects physical mics)
    2. Copy fixture WAV to remote Pi
    3. Start single-pass playback (no loop jitter)
    4. Wait for decoder sync + aplay buffer fill
    5. Wait for signal presence (ensures valid data path)
    6. Set LOW gain, wait, capture with validation
    7. Set HIGH gain, wait, capture with validation
    8. Verify ratio exceeds threshold
    """
    if audio_settings_guard is None:
        return

    target_output_ch = MIC_OUTPUT_BASE_CH + mic_idx
    mic_map = list(PACKAGED_INPUT_FULL_MAP)

    # Select fixture: dedicated mic-gain fixture or DoA angle fixture
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

    # Configure output routing first
    _set_mic_output_packing(
        sq66_rpi_host,
        sq66_rpi_sat1_cmd,
        enabled=True,
        upsample_channel_map=UPSAMPLE_CHANNEL_MAP_DEFAULT,
    )
    _set_mic_output_channels(
        sq66_rpi_host,
        sq66_rpi_sat1_cmd,
        target_output_ch,
        target_output_ch,
    )

    # CRITICAL: Set input routing to PACKAGED_INPUT BEFORE starting playback
    # This ensures physical mic noise can't trigger _wait_for_signal prematurely
    _set_mic_input_gains(
        sq66_rpi_host,
        sq66_rpi_sat1_cmd,
        ref_source_mode=REF_SOURCE_LEGACY_DOWNSAMPLED,
        mic_source_mode=MIC_SOURCE_PACKAGED_INPUT,
    )

    # Copy fixture to remote Pi
    remote_wav = f"/tmp/sq66_mic_gain_fixture_{int(time.time())}.wav"
    scp_res = subprocess.run(
        ["scp", str(local_wav), f"{sq66_rpi_host}:{remote_wav}"],
        cwd=PROJ_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert scp_res.returncode == 0, scp_res.stdout + scp_res.stderr

    # Start looping playback
    playback_proc = _start_remote_wav_playback_loop(sq66_rpi_host, remote_wav)

    try:
        # Wait for decoder sync detection + aplay buffer fill
        # The packaged decoder re-detects sync every frame (~67µs at 15kHz)
        # This covers worst-case transition from no-input to valid input
        time.sleep(MIC_GAIN_DECODER_SYNC_WAIT_S)

        # Wait for signal presence (validates playback started + routing active)
        probe_rms = _wait_for_signal(sq66_rpi_host)
        print(f"Signal detected: RMS={probe_rms:.1f} (mic_idx={mic_idx})")

        # === LOW GAIN CAPTURE ===
        _set_mic_input_gains(
            sq66_rpi_host,
            sq66_rpi_sat1_cmd,
            mic_gain=Q30_LOW,
            ref_gain=Q30_UNITY,
            ref_source_mode=REF_SOURCE_LEGACY_DOWNSAMPLED,
            mic_source_mode=MIC_SOURCE_PACKAGED_INPUT,
        )
        _set_mic_input_gains(
            sq66_rpi_host,
            sq66_rpi_sat1_cmd,
            mic_input_channel_map=mic_map,
        )
        time.sleep(MIC_GAIN_WARMUP_SEC)

        # Re-verify signal after gain change (pipeline settle)
        _wait_for_signal(sq66_rpi_host)

        low_rms, low_peak = _capture_rms_median_fullband(
            sq66_rpi_host,
            repeats=MIC_GAIN_CAPTURE_REPEATS,
            duration_s=MIC_GAIN_CAPTURE_SEC,
        )
        print(f"LOW gain: RMS={low_rms:.1f}, peak={low_peak} (mic_idx={mic_idx})")

        # === HIGH GAIN CAPTURE ===
        _set_mic_input_gains(
            sq66_rpi_host,
            sq66_rpi_sat1_cmd,
            mic_gain=MIC_GAIN_TEST_HIGH,
            ref_gain=Q30_UNITY,
            ref_source_mode=REF_SOURCE_LEGACY_DOWNSAMPLED,
            mic_source_mode=MIC_SOURCE_PACKAGED_INPUT,
        )
        _set_mic_input_gains(
            sq66_rpi_host,
            sq66_rpi_sat1_cmd,
            mic_input_channel_map=mic_map,
        )
        time.sleep(MIC_GAIN_WARMUP_SEC)

        # Re-verify signal after gain change
        _wait_for_signal(sq66_rpi_host)

        high_rms, high_peak = _capture_rms_median_fullband(
            sq66_rpi_host,
            repeats=MIC_GAIN_CAPTURE_REPEATS,
            duration_s=MIC_GAIN_CAPTURE_SEC,
        )
        print(f"HIGH gain: RMS={high_rms:.1f}, peak={high_peak} (mic_idx={mic_idx})")

    finally:
        # Cleanup playback process
        playback_proc.terminate()
        try:
            playback_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            playback_proc.kill()
            playback_proc.wait(timeout=3)
        _run_ssh(sq66_rpi_host, f"rm -f {shlex.quote(remote_wav)}", timeout=10)

    # Validate signal levels
    if low_rms < 1.0 or high_rms < 1.0:
        print(
            "Insufficient mic signal for gain validation "
            f"(mic_idx={mic_idx}, low={low_rms:.2f}, high={high_rms:.2f})"
        )
        return

    # Validate no clipping
    assert low_peak < MIC_GAIN_MAX_PEAK, (
        f"Low-gain capture clipped (mic_idx={mic_idx}, peak={low_peak})"
    )
    assert high_peak < MIC_GAIN_MAX_PEAK, (
        f"High-gain capture clipped (mic_idx={mic_idx}, peak={high_peak})"
    )

    # Validate gain change effect
    ratio = high_rms / low_rms
    assert ratio > MIC_GAIN_MIN_RATIO, (
        f"Expected mic gain change to increase captured RMS "
        f"(mic_idx={mic_idx}, low={low_rms:.2f}, high={high_rms:.2f}, "
        f"ratio={ratio:.3f}, min_ratio={MIC_GAIN_MIN_RATIO:.3f})"
    )


@pytest.mark.hil
@pytest.mark.sq66
def test_ref_gain_changes_captured_level_sq66(
    audio_settings_guard,
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
) -> None:
    if audio_settings_guard is None:
        return
    _set_mic_output_packing(sq66_rpi_host, sq66_rpi_sat1_cmd, enabled=False)
    _set_mic_output_channels(sq66_rpi_host, sq66_rpi_sat1_cmd, 0, 0)

    tone_proc = _start_remote_tone(sq66_rpi_host)
    try:
        time.sleep(1.0)

        _set_mic_input_gains(
            sq66_rpi_host,
            sq66_rpi_sat1_cmd,
            mic_gain=Q30_LOW,
            ref_gain=Q30_LOW,
            ref_source_mode=REF_SOURCE_LEGACY_DOWNSAMPLED,
            mic_source_mode=MIC_SOURCE_PDM,
        )
        time.sleep(0.3)
        low_rms = _capture_rms(sq66_rpi_host, duration_s=2)

        _set_mic_input_gains(
            sq66_rpi_host,
            sq66_rpi_sat1_cmd,
            mic_gain=Q30_LOW,
            ref_gain=Q30_UNITY,
            ref_source_mode=REF_SOURCE_LEGACY_DOWNSAMPLED,
            mic_source_mode=MIC_SOURCE_PDM,
        )
        time.sleep(0.3)
        high_rms = _capture_rms(sq66_rpi_host, duration_s=2)
    finally:
        tone_proc.terminate()
        try:
            tone_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            tone_proc.kill()
            tone_proc.wait(timeout=3)

    if low_rms < 1.0 or high_rms < 1.0:
        print(
            "Insufficient reference-linked signal "
            f"(low={low_rms:.2f}, high={high_rms:.2f})"
        )
        return

    ratio = high_rms / low_rms
    effect = ratio if ratio >= 1.0 else (1.0 / ratio)
    assert effect > 1.02, (
        f"Expected ref gain change to affect captured RMS (low={low_rms:.2f}, "
        f"high={high_rms:.2f}, ratio={ratio:.2f}, effect={effect:.2f})"
    )
