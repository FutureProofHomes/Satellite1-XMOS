import json
import os
import shlex
import subprocess
import time

import pytest

from tests.conftest import PROJ_ROOT


AUDIO_PIPELINE_OUTPUT_CHANNEL_COUNT = 2
AUDIO_PIPELINE_OUTPUT_CHANNEL_INDEX_MIN = 0
AUDIO_PIPELINE_OUTPUT_CHANNEL_INDEX_MAX = 7
AUDIO_PIPELINE_UPSAMPLE_CHANNEL_MAP_COUNT = 6
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


def _get_mic_output_settings(sq66_rpi_host: str, sq66_rpi_sat1_cmd: str) -> dict:
    script = """
import json
from satellite1.sat1_hat import XMOS

x = XMOS()
x.setup()
_ = x.read_firmware()
_ = x.wait_until_ready(timeout_s=3.0, poll_interval_s=0.1)
try:
    settings = x.get_mic_output_settings()
    data = {
        "pack_extra_upsample_channels": int(settings.pack_extra_upsample_channels),
        "i2s_channel_map": [int(v) for v in settings.i2s_channel_map],
        "upsample_channel_map": [int(v) for v in settings.upsample_channel_map],
    }
    print(json.dumps(data))
finally:
    cntrl = getattr(x, "_cntrl", None)
    if cntrl is not None and hasattr(cntrl, "close"):
        cntrl.close()
"""
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(RETRY_ATTEMPTS):
        last = _run_remote_sdk_python(
            sq66_rpi_host,
            sq66_rpi_sat1_cmd,
            script,
            timeout=REMOTE_SDK_TIMEOUT_S,
        )
        if last.returncode == 0:
            out = last.stdout.strip()
            if out:
                return json.loads(out.splitlines()[-1])
        if attempt < (RETRY_ATTEMPTS - 1):
            time.sleep(RETRY_DELAY_S)

    assert last is not None
    assert last.returncode == 0, last.stdout + last.stderr
    raise AssertionError("Expected mic output settings JSON from remote SDK")


def _set_mic_output_settings_partial(
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
    *,
    i2s_channel_map: list[int] | None = None,
    pack_extra_upsample_channels: int | None = None,
    upsample_channel_map: list[int] | None = None,
) -> None:
    payload = {
        "i2s_channel_map": i2s_channel_map,
        "pack_extra_upsample_channels": pack_extra_upsample_channels,
        "upsample_channel_map": upsample_channel_map,
    }
    payload_json = json.dumps(payload)

    script = f"""
import json
from satellite1.sat1_hat import XMOS

payload = json.loads({payload_json!r})
x = XMOS()
x.setup()
_ = x.read_firmware()
_ = x.wait_until_ready(timeout_s=3.0, poll_interval_s=0.1)
try:
    ok = True

    i2s = payload["i2s_channel_map"]
    if i2s is not None:
        ok = x.set_mic_output_channels(int(i2s[0]), int(i2s[1])) and ok

    pack = payload["pack_extra_upsample_channels"]
    upsample = payload["upsample_channel_map"]
    if pack is not None or upsample is not None:
        if pack is None:
            pack = int(x.get_mic_output_settings().pack_extra_upsample_channels)
        ok = x.set_mic_output_packing(bool(pack), upsample) and ok

    print(json.dumps({{"ok": bool(ok)}}))
finally:
    cntrl = getattr(x, "_cntrl", None)
    if cntrl is not None and hasattr(cntrl, "close"):
        cntrl.close()
"""
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(RETRY_ATTEMPTS):
        last = _run_remote_sdk_python(
            sq66_rpi_host,
            sq66_rpi_sat1_cmd,
            script,
            timeout=REMOTE_SDK_TIMEOUT_S,
        )
        if last.returncode == 0:
            out = last.stdout.strip()
            if out:
                body = json.loads(out.splitlines()[-1])
                if body.get("ok") is True:
                    return
        if attempt < (RETRY_ATTEMPTS - 1):
            time.sleep(RETRY_DELAY_S)

    assert last is not None
    assert last.returncode == 0, last.stdout + last.stderr
    raise AssertionError("mic output settings update did not report success")


def _alternate_pair(original: list[int]) -> list[int]:
    candidates = ([0, 1], [2, 3], [4, 5], [6, 7], [7, 6], [1, 0])
    for pair in candidates:
        if pair != original:
            return list(pair)
    return list(reversed(original))


def _alternate_upsample_map(original: list[int]) -> list[int]:
    candidates = (
        [0, 1, 2, 3, 4, 5],
        [5, 4, 3, 2, 1, 0],
        [1, 0, 3, 2, 5, 4],
    )
    for mapping in candidates:
        if mapping != original:
            return list(mapping)
    return list(reversed(original))


@pytest.fixture
def mic_output_settings_guard(
    require_sq66_hil: None,
    ensure_sq66_running: None,
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
):
    original = _get_mic_output_settings(sq66_rpi_host, sq66_rpi_sat1_cmd)
    yield original
    _set_mic_output_settings_partial(
        sq66_rpi_host,
        sq66_rpi_sat1_cmd,
        i2s_channel_map=original["i2s_channel_map"],
        pack_extra_upsample_channels=original["pack_extra_upsample_channels"],
        upsample_channel_map=original["upsample_channel_map"],
    )


@pytest.mark.hil
@pytest.mark.sq66
def test_mic_output_get_settings_shape_sq66(
    mic_output_settings_guard,
):
    settings = mic_output_settings_guard

    assert set(settings.keys()) == {
        "pack_extra_upsample_channels",
        "i2s_channel_map",
        "upsample_channel_map",
    }

    assert settings["pack_extra_upsample_channels"] in (0, 1)

    i2s = settings["i2s_channel_map"]
    assert len(i2s) == AUDIO_PIPELINE_OUTPUT_CHANNEL_COUNT
    assert all(
        AUDIO_PIPELINE_OUTPUT_CHANNEL_INDEX_MIN
        <= ch
        <= AUDIO_PIPELINE_OUTPUT_CHANNEL_INDEX_MAX
        for ch in i2s
    )

    upsample = settings["upsample_channel_map"]
    assert len(upsample) == AUDIO_PIPELINE_UPSAMPLE_CHANNEL_MAP_COUNT
    assert all(
        AUDIO_PIPELINE_OUTPUT_CHANNEL_INDEX_MIN
        <= ch
        <= AUDIO_PIPELINE_OUTPUT_CHANNEL_INDEX_MAX
        for ch in upsample
    )


@pytest.mark.hil
@pytest.mark.sq66
def test_mic_output_set_i2s_channel_map_roundtrip_sq66(
    mic_output_settings_guard,
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
):
    original = mic_output_settings_guard
    target_pair = _alternate_pair(original["i2s_channel_map"])

    _set_mic_output_settings_partial(
        sq66_rpi_host,
        sq66_rpi_sat1_cmd,
        i2s_channel_map=target_pair,
    )

    actual = _get_mic_output_settings(sq66_rpi_host, sq66_rpi_sat1_cmd)
    assert actual["i2s_channel_map"] == target_pair


@pytest.mark.hil
@pytest.mark.sq66
def test_mic_output_set_pack_extra_roundtrip_sq66(
    mic_output_settings_guard,
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
):
    original = mic_output_settings_guard
    target = 0 if original["pack_extra_upsample_channels"] else 1

    _set_mic_output_settings_partial(
        sq66_rpi_host,
        sq66_rpi_sat1_cmd,
        pack_extra_upsample_channels=target,
    )

    actual = _get_mic_output_settings(sq66_rpi_host, sq66_rpi_sat1_cmd)
    assert actual["pack_extra_upsample_channels"] == target


@pytest.mark.hil
@pytest.mark.sq66
def test_mic_output_set_upsample_channel_map_roundtrip_sq66(
    mic_output_settings_guard,
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
):
    original = mic_output_settings_guard
    target_map = _alternate_upsample_map(original["upsample_channel_map"])

    _set_mic_output_settings_partial(
        sq66_rpi_host,
        sq66_rpi_sat1_cmd,
        upsample_channel_map=target_map,
    )

    actual = _get_mic_output_settings(sq66_rpi_host, sq66_rpi_sat1_cmd)
    assert actual["upsample_channel_map"] == target_map


@pytest.mark.hil
@pytest.mark.sq66
def test_mic_output_partial_update_preserves_untouched_fields_sq66(
    mic_output_settings_guard,
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
):
    original = mic_output_settings_guard
    target_pair = _alternate_pair(original["i2s_channel_map"])

    _set_mic_output_settings_partial(
        sq66_rpi_host,
        sq66_rpi_sat1_cmd,
        i2s_channel_map=target_pair,
    )

    actual = _get_mic_output_settings(sq66_rpi_host, sq66_rpi_sat1_cmd)
    assert actual["i2s_channel_map"] == target_pair
    assert (
        actual["pack_extra_upsample_channels"]
        == original["pack_extra_upsample_channels"]
    )
    assert actual["upsample_channel_map"] == original["upsample_channel_map"]
