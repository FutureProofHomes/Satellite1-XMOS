import json
import shlex
import subprocess
import time

import pytest

from tests.conftest import PROJ_ROOT
from tests.test_hil.conftest import hil_env_float, hil_env_int


AUDIO_PIPELINE_OUTPUT_CHANNEL_COUNT = 2
AUDIO_PIPELINE_OUTPUT_CHANNEL_INDEX_MIN = 0
AUDIO_PIPELINE_OUTPUT_CHANNEL_INDEX_MAX = 7
AUDIO_PIPELINE_UPSAMPLE_CHANNEL_MAP_COUNT = 6


def _hil_timeouts(hil_board: str) -> dict[str, int | float]:
    return {
        "ssh_connect_timeout_s": hil_env_int(hil_board, "SSH_CONNECT_TIMEOUT_S", 5),
        "ssh_cmd_timeout_s": hil_env_int(hil_board, "SSH_TIMEOUT_S", 30),
        "remote_cli_timeout_s": hil_env_int(hil_board, "REMOTE_SDK_TIMEOUT_S", 40),
        "retry_attempts": hil_env_int(hil_board, "RETRY_ATTEMPTS", 4),
        "retry_delay_s": hil_env_float(hil_board, "RETRY_DELAY_S", 0.5),
    }


def _run_ssh(
    host: str,
    cmd: str,
    *,
    ssh_connect_timeout_s: int,
    ssh_cmd_timeout_s: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={ssh_connect_timeout_s}",
            host,
            cmd,
        ],
        cwd=PROJ_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=ssh_cmd_timeout_s,
    )


def _get_mic_output_settings(
    hil_rpi_host: str, hil_cli_cmd: str, *, timeouts: dict[str, int | float]
) -> dict:
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(int(timeouts["retry_attempts"])):
        last = _run_ssh(
            hil_rpi_host,
            f"{hil_cli_cmd} xmos get-mic-pipeline-settings --json",
            ssh_connect_timeout_s=int(timeouts["ssh_connect_timeout_s"]),
            ssh_cmd_timeout_s=int(timeouts["remote_cli_timeout_s"]),
        )
        if last.returncode == 0:
            out = last.stdout.strip()
            if out:
                body = json.loads(out.splitlines()[-1])
                return dict(body["mic_output"])
        if attempt < (int(timeouts["retry_attempts"]) - 1):
            time.sleep(float(timeouts["retry_delay_s"]))

    assert last is not None
    assert last.returncode == 0, last.stdout + last.stderr
    raise AssertionError("Expected mic output settings JSON from remote CLI")


def _set_mic_output_settings_partial(
    hil_rpi_host: str,
    hil_cli_cmd: str,
    *,
    i2s_channel_map: list[int] | None = None,
    pack_extra_upsample_channels: int | None = None,
    overwrite_ref_with_ic_ns_output: int | None = None,
    upsample_channel_map: list[int] | None = None,
    timeouts: dict[str, int | float],
) -> None:
    mic_output: dict[str, object] = {}
    if i2s_channel_map is not None:
        mic_output["i2s_channel_map"] = [int(v) for v in i2s_channel_map]
    if pack_extra_upsample_channels is not None:
        mic_output["pack_extra_upsample_channels"] = int(pack_extra_upsample_channels)
    if overwrite_ref_with_ic_ns_output is not None:
        mic_output["overwrite_ref_with_ic_ns_output"] = int(
            overwrite_ref_with_ic_ns_output
        )
    if upsample_channel_map is not None:
        mic_output["upsample_channel_map"] = [int(v) for v in upsample_channel_map]
    payload_json = json.dumps({"mic_output": mic_output}, separators=(",", ":"))

    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(int(timeouts["retry_attempts"])):
        last = _run_ssh(
            hil_rpi_host,
            f"{hil_cli_cmd} xmos set-mic-pipeline-settings --json {shlex.quote(payload_json)}",
            ssh_connect_timeout_s=int(timeouts["ssh_connect_timeout_s"]),
            ssh_cmd_timeout_s=int(timeouts["remote_cli_timeout_s"]),
        )
        if last.returncode == 0:
            if "True" in last.stdout:
                return
        if attempt < (int(timeouts["retry_attempts"]) - 1):
            time.sleep(float(timeouts["retry_delay_s"]))

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
    require_hil: None,
    hil_board: str,
    hil_rpi_host: str,
    hil_cli_cmd: str,
):
    timeouts = _hil_timeouts(hil_board)
    original = _get_mic_output_settings(
        hil_rpi_host,
        hil_cli_cmd,
        timeouts=timeouts,
    )
    yield original
    _set_mic_output_settings_partial(
        hil_rpi_host,
        hil_cli_cmd,
        i2s_channel_map=original["i2s_channel_map"],
        pack_extra_upsample_channels=original["pack_extra_upsample_channels"],
        overwrite_ref_with_ic_ns_output=original["overwrite_ref_with_ic_ns_output"],
        upsample_channel_map=original["upsample_channel_map"],
        timeouts=timeouts,
    )


@pytest.mark.hil
def test_hil_device_control_mic_output_get_settings_shape(
    mic_output_settings_guard,
):
    settings = mic_output_settings_guard

    assert set(settings.keys()) == {
        "pack_extra_upsample_channels",
        "overwrite_ref_with_ic_ns_output",
        "i2s_channel_map",
        "upsample_channel_map",
    }

    assert settings["pack_extra_upsample_channels"] in (0, 1)
    assert settings["overwrite_ref_with_ic_ns_output"] in (0, 1)

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
def test_hil_device_control_mic_output_set_i2s_channel_map_roundtrip(
    mic_output_settings_guard,
    hil_board: str,
    hil_rpi_host: str,
    hil_cli_cmd: str,
):
    original = mic_output_settings_guard
    target_pair = _alternate_pair(original["i2s_channel_map"])

    _set_mic_output_settings_partial(
        hil_rpi_host,
        hil_cli_cmd,
        i2s_channel_map=target_pair,
        timeouts=_hil_timeouts(hil_board),
    )

    actual = _get_mic_output_settings(
        hil_rpi_host,
        hil_cli_cmd,
        timeouts=_hil_timeouts(hil_board),
    )
    assert actual["i2s_channel_map"] == target_pair


@pytest.mark.hil
def test_hil_device_control_mic_output_set_pack_extra_roundtrip(
    mic_output_settings_guard,
    hil_board: str,
    hil_rpi_host: str,
    hil_cli_cmd: str,
):
    original = mic_output_settings_guard
    target = 0 if original["pack_extra_upsample_channels"] else 1

    _set_mic_output_settings_partial(
        hil_rpi_host,
        hil_cli_cmd,
        pack_extra_upsample_channels=target,
        timeouts=_hil_timeouts(hil_board),
    )

    actual = _get_mic_output_settings(
        hil_rpi_host,
        hil_cli_cmd,
        timeouts=_hil_timeouts(hil_board),
    )
    assert actual["pack_extra_upsample_channels"] == target


@pytest.mark.hil
def test_hil_device_control_mic_output_set_ref_overwrite_roundtrip(
    mic_output_settings_guard,
    hil_board: str,
    hil_rpi_host: str,
    hil_cli_cmd: str,
):
    original = mic_output_settings_guard
    target = 0 if original["overwrite_ref_with_ic_ns_output"] else 1

    _set_mic_output_settings_partial(
        hil_rpi_host,
        hil_cli_cmd,
        overwrite_ref_with_ic_ns_output=target,
        timeouts=_hil_timeouts(hil_board),
    )

    actual = _get_mic_output_settings(
        hil_rpi_host,
        hil_cli_cmd,
        timeouts=_hil_timeouts(hil_board),
    )
    assert actual["overwrite_ref_with_ic_ns_output"] == target


@pytest.mark.hil
def test_hil_device_control_mic_output_set_upsample_channel_map_roundtrip(
    mic_output_settings_guard,
    hil_board: str,
    hil_rpi_host: str,
    hil_cli_cmd: str,
):
    original = mic_output_settings_guard
    target_map = _alternate_upsample_map(original["upsample_channel_map"])

    _set_mic_output_settings_partial(
        hil_rpi_host,
        hil_cli_cmd,
        upsample_channel_map=target_map,
        timeouts=_hil_timeouts(hil_board),
    )

    actual = _get_mic_output_settings(
        hil_rpi_host,
        hil_cli_cmd,
        timeouts=_hil_timeouts(hil_board),
    )
    assert actual["upsample_channel_map"] == target_map


@pytest.mark.hil
def test_hil_device_control_mic_output_partial_update_preserves_untouched_fields(
    mic_output_settings_guard,
    hil_board: str,
    hil_rpi_host: str,
    hil_cli_cmd: str,
):
    original = mic_output_settings_guard
    target_pair = _alternate_pair(original["i2s_channel_map"])

    _set_mic_output_settings_partial(
        hil_rpi_host,
        hil_cli_cmd,
        i2s_channel_map=target_pair,
        timeouts=_hil_timeouts(hil_board),
    )

    actual = _get_mic_output_settings(
        hil_rpi_host,
        hil_cli_cmd,
        timeouts=_hil_timeouts(hil_board),
    )
    assert actual["i2s_channel_map"] == target_pair
    assert (
        actual["pack_extra_upsample_channels"]
        == original["pack_extra_upsample_channels"]
    )
    assert (
        actual["overwrite_ref_with_ic_ns_output"]
        == original["overwrite_ref_with_ic_ns_output"]
    )
    assert actual["upsample_channel_map"] == original["upsample_channel_map"]
