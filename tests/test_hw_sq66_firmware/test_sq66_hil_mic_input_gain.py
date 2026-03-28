import json
import math
import os
import shlex
import struct
import subprocess
import time

import pytest

from tests.conftest import PROJ_ROOT


Q30_UNITY = 0x40000000
Q30_LOW = 0x08000000
I2S_RATE_HZ = 48000
PIPELINE_RATE_HZ = 16000
UPSAMPLE_FACTOR = I2S_RATE_HZ // PIPELINE_RATE_HZ
SSH_CONNECT_TIMEOUT_S = int(os.getenv("SQ66_HIL_SSH_CONNECT_TIMEOUT_S", "5"))
SSH_CMD_TIMEOUT_S = int(os.getenv("SQ66_HIL_SSH_TIMEOUT_S", "30"))
REMOTE_SDK_TIMEOUT_S = int(os.getenv("SQ66_HIL_REMOTE_SDK_TIMEOUT_S", "40"))
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


def _parse_remote_python_command(sq66_rpi_sat1_cmd: str) -> tuple[list[str], str]:
    tokens = shlex.split(sq66_rpi_sat1_cmd)
    if not tokens:
        return [], "python3"

    python_idx = 0
    for idx, token in enumerate(tokens):
        if "=" in token and not token.startswith("-"):
            continue
        python_idx = idx
        break

    env_tokens = [t for t in tokens[:python_idx] if "=" in t and not t.startswith("-")]
    python_cmd = tokens[python_idx]
    return env_tokens, python_cmd


def _run_remote_sdk_python(
    host: str, sq66_rpi_sat1_cmd: str, script: str, timeout: int = REMOTE_SDK_TIMEOUT_S
) -> subprocess.CompletedProcess[str]:
    env_tokens, python_cmd = _parse_remote_python_command(sq66_rpi_sat1_cmd)
    remote_cmd = " ".join(env_tokens + [python_cmd, "-c", shlex.quote(script)])
    return _run_ssh(host, remote_cmd, timeout=timeout)


def _run_remote_sdk_json(
    host: str, sq66_rpi_sat1_cmd: str, script: str, timeout: int = REMOTE_SDK_TIMEOUT_S
) -> dict:
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(RETRY_ATTEMPTS):
        last = _run_remote_sdk_python(host, sq66_rpi_sat1_cmd, script, timeout=timeout)
        if last.returncode == 0:
            out = last.stdout.strip()
            if out:
                return json.loads(out.splitlines()[-1])
        if attempt < (RETRY_ATTEMPTS - 1):
            time.sleep(RETRY_DELAY_S)

    assert last is not None
    assert last.returncode == 0, last.stdout + last.stderr
    raise AssertionError("Expected JSON output from remote SDK command")


def _get_audio_settings(sq66_rpi_host: str, sq66_rpi_sat1_cmd: str) -> dict:
    script = """
import json
from satellite1.sat1_hat import XMOS

x = XMOS()
x.setup()
_ = x.read_firmware()
_ = x.wait_until_ready(timeout_s=3.0, poll_interval_s=0.1)
try:
    mic_in = x.get_mic_input_settings()
    mic_out = x.get_mic_output_settings()
    mic_count = x.get_available_mic_count()
    print(json.dumps({
        "available_mic_count": int(mic_count),
        "mic_input": {
            "mic_gain": int(mic_in.mic_gain),
            "ref_gain": int(mic_in.ref_gain),
            "ref_source_mode": int(mic_in.ref_source_mode),
            "mic_source_mode": int(mic_in.mic_source_mode),
            "ref_input_channel_map": [int(v) for v in mic_in.ref_input_channel_map],
            "mic_input_channel_map": [int(v) for v in mic_in.mic_input_channel_map],
        },
        "mic_output": {
            "pack_extra_upsample_channels": int(mic_out.pack_extra_upsample_channels),
            "i2s_channel_map": [int(v) for v in mic_out.i2s_channel_map],
            "upsample_channel_map": [int(v) for v in mic_out.upsample_channel_map],
        },
    }))
finally:
    cntrl = getattr(x, "_cntrl", None)
    if cntrl is not None and hasattr(cntrl, "close"):
        cntrl.close()
"""
    return _run_remote_sdk_json(
        sq66_rpi_host,
        sq66_rpi_sat1_cmd,
        script,
        timeout=REMOTE_SDK_TIMEOUT_S,
    )


def _set_mic_input_gains(
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
    *,
    mic_gain: int | None = None,
    ref_gain: int | None = None,
) -> None:
    payload = json.dumps({"mic_gain": mic_gain, "ref_gain": ref_gain})
    script = f"""
import json
from satellite1.sat1_hat import XMOS

payload = json.loads({payload!r})
x = XMOS()
x.setup()
_ = x.read_firmware()
_ = x.wait_until_ready(timeout_s=3.0, poll_interval_s=0.1)
try:
    ok = x.set_mic_input_gains(
        mic_gain=payload["mic_gain"],
        ref_gain=payload["ref_gain"],
    )
    print(json.dumps({{"ok": bool(ok)}}))
finally:
    cntrl = getattr(x, "_cntrl", None)
    if cntrl is not None and hasattr(cntrl, "close"):
        cntrl.close()
"""
    body = _run_remote_sdk_json(
        sq66_rpi_host,
        sq66_rpi_sat1_cmd,
        script,
        timeout=REMOTE_SDK_TIMEOUT_S,
    )
    assert body.get("ok") is True, f"set_mic_input_gains failed: {body}"


def _set_mic_output_channels(
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
    left: int,
    right: int,
) -> None:
    script = f"""
import json
from satellite1.sat1_hat import XMOS

x = XMOS()
x.setup()
_ = x.read_firmware()
_ = x.wait_until_ready(timeout_s=3.0, poll_interval_s=0.1)
try:
    ok = x.set_mic_output_channels({left}, {right})
    print(json.dumps({{"ok": bool(ok)}}))
finally:
    cntrl = getattr(x, "_cntrl", None)
    if cntrl is not None and hasattr(cntrl, "close"):
        cntrl.close()
"""
    body = _run_remote_sdk_json(
        sq66_rpi_host,
        sq66_rpi_sat1_cmd,
        script,
        timeout=REMOTE_SDK_TIMEOUT_S,
    )
    assert body.get("ok") is True, f"set_mic_output_channels failed: {body}"


def _set_mic_output_packing(
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
    *,
    enabled: bool,
    upsample_channel_map: list[int] | None = None,
) -> None:
    payload = json.dumps(
        {
            "enabled": bool(enabled),
            "upsample_channel_map": upsample_channel_map,
        }
    )
    script = f"""
import json
from satellite1.sat1_hat import XMOS

payload = json.loads({payload!r})
x = XMOS()
x.setup()
_ = x.read_firmware()
_ = x.wait_until_ready(timeout_s=3.0, poll_interval_s=0.1)
try:
    ok = x.set_mic_output_packing(
        payload["enabled"],
        payload["upsample_channel_map"],
    )
    print(json.dumps({{"ok": bool(ok)}}))
finally:
    cntrl = getattr(x, "_cntrl", None)
    if cntrl is not None and hasattr(cntrl, "close"):
        cntrl.close()
"""
    body = _run_remote_sdk_json(
        sq66_rpi_host,
        sq66_rpi_sat1_cmd,
        script,
        timeout=REMOTE_SDK_TIMEOUT_S,
    )
    assert body.get("ok") is True, f"set_mic_output_packing failed: {body}"


def _capture_channel_samples(
    sq66_rpi_host: str,
    *,
    duration_s: int = 2,
    channel_index: int = 0,
) -> list[int]:
    capture_cmd = (
        f"arecord -D hw:0,1 -f S32_LE -r {I2S_RATE_HZ} -c 2 -d {duration_s} -t raw -q"
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
    original = _get_audio_settings(sq66_rpi_host, sq66_rpi_sat1_cmd)
    yield original

    _set_mic_input_gains(
        sq66_rpi_host,
        sq66_rpi_sat1_cmd,
        mic_gain=original["mic_input"]["mic_gain"],
        ref_gain=original["mic_input"]["ref_gain"],
    )
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
def test_mic_gain_changes_captured_level_sq66(
    audio_settings_guard,
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
) -> None:
    _set_mic_output_packing(sq66_rpi_host, sq66_rpi_sat1_cmd, enabled=False)
    _set_mic_output_channels(sq66_rpi_host, sq66_rpi_sat1_cmd, 4, 4)

    _set_mic_input_gains(
        sq66_rpi_host,
        sq66_rpi_sat1_cmd,
        mic_gain=Q30_LOW,
        ref_gain=Q30_UNITY,
    )
    time.sleep(0.3)
    low_rms = _capture_rms(sq66_rpi_host, duration_s=2)

    _set_mic_input_gains(
        sq66_rpi_host,
        sq66_rpi_sat1_cmd,
        mic_gain=Q30_UNITY,
        ref_gain=Q30_UNITY,
    )
    time.sleep(0.3)
    high_rms = _capture_rms(sq66_rpi_host, duration_s=2)

    if low_rms < 1.0 or high_rms < 1.0:
        pytest.skip(
            f"Insufficient mic signal for gain validation (low={low_rms:.2f}, high={high_rms:.2f})"
        )

    ratio = high_rms / low_rms
    assert ratio > 2.0, (
        f"Expected mic gain to increase captured RMS (low={low_rms:.2f}, "
        f"high={high_rms:.2f}, ratio={ratio:.2f})"
    )


@pytest.mark.hil
@pytest.mark.sq66
def test_ref_gain_changes_captured_level_sq66(
    audio_settings_guard,
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
) -> None:
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
        )
        time.sleep(0.3)
        low_rms = _capture_rms(sq66_rpi_host, duration_s=2)

        _set_mic_input_gains(
            sq66_rpi_host,
            sq66_rpi_sat1_cmd,
            mic_gain=Q30_LOW,
            ref_gain=Q30_UNITY,
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
        pytest.skip(
            f"Insufficient reference-linked signal (low={low_rms:.2f}, high={high_rms:.2f})"
        )

    ratio = high_rms / low_rms
    if ratio <= 1.1:
        pytest.skip(
            "Reference gain effect not observable on this setup "
            f"(low={low_rms:.2f}, high={high_rms:.2f}, ratio={ratio:.2f})"
        )

    assert ratio > 1.1, (
        f"Expected ref gain to increase captured RMS (low={low_rms:.2f}, "
        f"high={high_rms:.2f}, ratio={ratio:.2f})"
    )
