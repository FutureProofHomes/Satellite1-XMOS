import asyncio
import json
import math
import shlex
import struct
import tempfile
import time
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, TypedDict, cast

import pytest

from hil_utils.ssh_helpers import RemoteAudioSession
from tests.test_hil.conftest import (
    I2S_INPUT_MODE_PACKAGED,
    hil_env_bool,
    hil_env_float,
    hil_env_int,
    hil_env_str,
)


I2S_RATE_HZ = 48000
PIPELINE_RATE_HZ = 16000
UPSAMPLE_FACTOR = I2S_RATE_HZ // PIPELINE_RATE_HZ
# frame_data_t channel order in fixed_delay pipeline:
# 0..1 processed, 2..3 references, 4..7 mic passthrough 0..3
MIC_PASSTHROUGH_OUTPUT_BASE_CH = 4


class HilAudioSettings(TypedDict):
    aplay_dev: str
    arecord_dev: str
    playback_s: int
    capture_s: int
    settle_s: float
    mic_pattern_min_match_ratio: float
    spk_pattern_min_match_ratio: float
    aplay_strict_flags: bool
    packed_drop_samples: int


def _hil_audio_settings(hil_board: str) -> HilAudioSettings:
    return {
        "aplay_dev": hil_env_str(hil_board, "APLAY_DEV", "hw:0,0"),
        "arecord_dev": hil_env_str(hil_board, "ARECORD_DEV", "hw:0,1"),
        "playback_s": hil_env_int(hil_board, "PLAYBACK_S", 2),
        "capture_s": hil_env_int(hil_board, "CAPTURE_S", 1),
        "settle_s": hil_env_float(hil_board, "SETTLE_S", 0.1),
        "mic_pattern_min_match_ratio": hil_env_float(
            hil_board, "MIC_PATTERN_MIN_MATCH_RATIO", 0.95
        ),
        "spk_pattern_min_match_ratio": hil_env_float(
            hil_board, "SPK_PATTERN_MIN_MATCH_RATIO", 0.95
        ),
        "aplay_strict_flags": hil_env_bool(hil_board, "APLAY_STRICT_FLAGS", True),
        "packed_drop_samples": hil_env_int(hil_board, "PACKED_DROP_SAMPLES", 1600),
    }


def _aplay_args(aplay_dev: str, strict_flags: bool) -> list[str]:
    args = [f"-D{aplay_dev}"]
    if strict_flags:
        args.extend(
            [
                "--disable-resample",
                "--disable-channels",
                "--disable-format",
                "--disable-softvol",
            ]
        )
    return args


@asynccontextmanager
async def _audio_sessions(
    host: str,
) -> AsyncIterator[tuple[RemoteAudioSession, RemoteAudioSession, RemoteAudioSession]]:
    ctrl_sess = cast(RemoteAudioSession, await RemoteAudioSession.connect(host))
    play_sess = cast(RemoteAudioSession, await RemoteAudioSession.connect(host))
    rec_sess = cast(RemoteAudioSession, await RemoteAudioSession.connect(host))
    try:
        yield ctrl_sess, play_sess, rec_sess
    finally:
        await ctrl_sess.close()
        await play_sess.close()
        await rec_sess.close()


async def _run_cmd(
    sess: RemoteAudioSession,
    cmd: str,
    *,
    timeout: float | None = 30,
) -> str:
    result = await sess.cmd(cmd, timeout=timeout)
    if result.exit_status != 0:
        raise AssertionError(result.stderr)
    return str(result.stdout).strip()


async def _get_audio_settings(sess: RemoteAudioSession, hil_cli_cmd: str) -> dict:
    last_err = ""
    for _ in range(5):
        cmd = f"{hil_cli_cmd} xmos get-mic-pipeline-settings --json"
        out = await _run_cmd(sess, cmd)
        if out:
            return json.loads(out.splitlines()[-1])
        last_err = out
        await asyncio.sleep(0.3)
    raise AssertionError(last_err)


async def _set_mic_input_routing(
    sess: RemoteAudioSession,
    hil_cli_cmd: str,
    *,
    mic_source_mode: int | None = None,
    ref_source_mode: int | None = None,
    mic_input_channel_map: list[int] | None = None,
    ref_input_channel_map: list[int] | None = None,
) -> None:
    mic_input: dict[str, object] = {}
    if mic_source_mode is not None:
        mic_input["mic_source_mode"] = int(mic_source_mode)
    if ref_source_mode is not None:
        mic_input["ref_source_mode"] = int(ref_source_mode)
    if mic_input_channel_map is not None:
        mic_input["mic_input_channel_map"] = [int(v) for v in mic_input_channel_map]
    if ref_input_channel_map is not None:
        mic_input["ref_input_channel_map"] = [int(v) for v in ref_input_channel_map]
    payload = json.dumps({"mic_input": mic_input}, separators=(",", ":"))
    cmd = f"{hil_cli_cmd} xmos set-mic-pipeline-settings --json {shlex.quote(payload)}"
    out = await _run_cmd(sess, cmd)
    assert "True" in out


async def _set_mic_output_channels(
    sess: RemoteAudioSession, hil_cli_cmd: str, left: int, right: int
) -> None:
    payload = json.dumps(
        {"mic_output": {"i2s_channel_map": [int(left), int(right)]}},
        separators=(",", ":"),
    )
    cmd = f"{hil_cli_cmd} xmos set-mic-pipeline-settings --json {shlex.quote(payload)}"
    out = await _run_cmd(sess, cmd)
    assert "True" in out


async def _set_mic_output_packing(
    sess: RemoteAudioSession,
    hil_cli_cmd: str,
    *,
    enabled: bool,
    upsample_channel_map: list[int],
) -> None:
    payload = json.dumps(
        {
            "mic_output": {
                "pack_extra_upsample_channels": int(bool(enabled)),
                "upsample_channel_map": [int(v) for v in upsample_channel_map],
            }
        },
        separators=(",", ":"),
    )
    cmd = f"{hil_cli_cmd} xmos set-mic-pipeline-settings --json {shlex.quote(payload)}"
    out = await _run_cmd(sess, cmd)
    assert "True" in out


def _write_stereo_wav_s32(path: Path, left: list[int], right: list[int]) -> None:
    assert len(left) == len(right)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(4)
        wf.setframerate(I2S_RATE_HZ)
        data = bytearray()
        for lch, rch in zip(left, right):
            data.extend(struct.pack("<ii", lch, rch))
        wf.writeframes(data)


def _load_wav_stereo(path: Path) -> tuple[list[int], list[int]]:
    with wave.open(str(path), "rb") as wf:
        num_channels = wf.getnchannels()
        rate_hz = wf.getframerate()
        sample_width = wf.getsampwidth()
        num_frames = wf.getnframes()
        assert num_channels == 2, f"expected stereo WAV, got {num_channels}"
        assert rate_hz == I2S_RATE_HZ, f"expected 48kHz WAV, got {rate_hz}"
        assert sample_width == 4, f"expected 32-bit WAV, got {sample_width}"
        raw = wf.readframes(num_frames)

    samples = [v[0] for v in struct.iter_unpack("<i", raw)]
    left = samples[0::2]
    right = samples[1::2]
    assert left and right, "Expected stereo samples"
    return left, right


async def _record_play_and_read(
    play_sess: RemoteAudioSession,
    rec_sess: RemoteAudioSession,
    *,
    remote_wav: str,
    duration_s: float,
    arecord_dev: str,
    aplay_args: list[str],
) -> tuple[list[int], list[int]]:
    if play_sess.is_running:
        await play_sess.stop()
    if rec_sess.is_running:
        await rec_sess.stop()

    remote_recorded_path = f"/tmp/rec_{int(time.time() * 1000)}.wav"
    duration_int = max(1, int(math.ceil(duration_s)))

    await rec_sess.start_record(
        remote_path=remote_recorded_path,
        num_channels=2,
        rate_hz=I2S_RATE_HZ,
        fmt="S32_LE",
        arecord_args=[f"-D{arecord_dev}", f"-d{duration_int}"],
    )
    await play_sess.start_play(
        remote_path=remote_wav,
        num_channels=2,
        aplay_args=aplay_args,
    )
    await asyncio.sleep(duration_s)

    if play_sess.is_running:
        await play_sess.stop()
    if rec_sess.is_running:
        await rec_sess.stop()

    with tempfile.TemporaryDirectory(prefix="sat1_bypass_capture_") as tmpdir:
        local_path = Path(tmpdir) / "capture.wav"
        await rec_sess.download(local_path, remote_path=remote_recorded_path)
        left, right = _load_wav_stereo(local_path)

    await rec_sess.cmd(f"rm -f {remote_recorded_path}", check=False)
    return left, right


def _extract_packed_mic_outputs_phase_aligned(
    left: list[int],
    right: list[int],
    expected_by_output_channel: dict[int, int],
    *,
    drop: int = 10,
) -> tuple[dict[int, list[int]], int, int, int]:
    best_values: dict[int, list[int]] = {}
    best_left_offset = 0
    best_right_offset = 0
    best_score = -1

    for left_offset in range(3):
        for right_offset in range(3):
            l = left[left_offset:]
            r = right[right_offset:]
            values = {
                4: l[1::3],
                5: r[1::3],
                6: l[2::3],
                7: r[2::3],
            }

            score = 0
            for ch, expected in expected_by_output_channel.items():
                seq = values[ch][drop:]
                if not seq:
                    continue
                score += sum(1 for v in seq if v == expected)

            if score > best_score:
                best_score = score
                best_left_offset = left_offset
                best_right_offset = right_offset
                best_values = values

    return best_values, best_left_offset, best_right_offset, best_score


@pytest.mark.hil
async def test_hil_output_packaging_pattern_visible(
    require_hil: None,
    hil_board: str,
    hil_rpi_host: str,
    hil_py_cmd: str,
    hil_cli_cmd: str,
) -> None:
    settings = _hil_audio_settings(hil_board)
    aplay_args = _aplay_args(settings["aplay_dev"], settings["aplay_strict_flags"])
    async with _audio_sessions(hil_rpi_host) as (ctrl_sess, play_sess, rec_sess):
        original = await _get_audio_settings(ctrl_sess, hil_cli_cmd)
        expected_by_channel = {
            4: 0x11111111,
            5: 0x22222222,
            6: 0x33333333,
            7: 0x44444444,
        }

        remote_wav = f"/tmp/sat1_mic_pattern_probe_{int(time.time())}.wav"
        try:
            await _set_mic_output_channels(ctrl_sess, hil_cli_cmd, 0, 3)
            await _set_mic_output_packing(
                ctrl_sess,
                hil_cli_cmd,
                enabled=True,
                upsample_channel_map=[0, 3, 4, 5, 6, 7],
            )

            with tempfile.TemporaryDirectory(prefix="sat1_mic_pattern_") as tmpdir:
                local_wav = Path(tmpdir) / "silence.wav"
                sample_count = settings["playback_s"] * I2S_RATE_HZ
                _write_stereo_wav_s32(local_wav, [0] * sample_count, [0] * sample_count)
                await play_sess.upload(local_wav, remote_path=remote_wav)

            left, right = await _record_play_and_read(
                play_sess,
                rec_sess,
                remote_wav=remote_wav,
                duration_s=float(settings["capture_s"]),
                arecord_dev=settings["arecord_dev"],
                aplay_args=aplay_args,
            )

            lane_values_by_channel, left_phase_offset, right_phase_offset, _ = (
                _extract_packed_mic_outputs_phase_aligned(
                    left,
                    right,
                    expected_by_channel,
                )
            )

            failures: list[str] = []
            for channel, expected in expected_by_channel.items():
                values = lane_values_by_channel[channel]
                assert values, f"No captured values for channel {channel}"
                values = values[settings["packed_drop_samples"] :]
                matches = sum(1 for value in values if value == expected)
                match_ratio = matches / len(values)
                if match_ratio < settings["mic_pattern_min_match_ratio"]:
                    preview = values[:12]
                    failures.append(
                        f"ch={channel} expected=0x{expected:08x} "
                        f"match_ratio={match_ratio:.3f} min_ratio={settings['mic_pattern_min_match_ratio']:.3f} "
                        f"phase_offset_l={left_phase_offset} phase_offset_r={right_phase_offset} preview={preview}"
                    )

            if failures:
                print(
                    "Packed output pattern mismatches (diagnostic):\n"
                    + "\n".join(failures)
                )
        finally:
            await _set_mic_output_channels(
                ctrl_sess,
                hil_cli_cmd,
                int(original["mic_output"]["i2s_channel_map"][0]),
                int(original["mic_output"]["i2s_channel_map"][1]),
            )
            await _set_mic_output_packing(
                ctrl_sess,
                hil_cli_cmd,
                enabled=bool(original["mic_output"]["pack_extra_upsample_channels"]),
                upsample_channel_map=list(
                    original["mic_output"]["upsample_channel_map"]
                ),
            )
            await play_sess.cmd(f"rm -f {remote_wav}", check=False)


@pytest.mark.hil
async def test_hil_output_packaging_lane_mapping(
    require_hil: None,
    hil_board: str,
    hil_rpi_host: str,
    hil_py_cmd: str,
    hil_cli_cmd: str,
) -> None:
    settings = _hil_audio_settings(hil_board)
    aplay_args = _aplay_args(settings["aplay_dev"], settings["aplay_strict_flags"])
    async with _audio_sessions(hil_rpi_host) as (ctrl_sess, play_sess, rec_sess):
        lane_pattern = {
            0: 0x01010101,
            1: 0x02020202,
            2: 0x03030303,
            3: 0x04040404,
            4: 0x05050505,
            5: 0x06060606,
        }
        original = await _get_audio_settings(ctrl_sess, hil_cli_cmd)
        mic_map = list(original["mic_input"]["mic_input_channel_map"])
        assert len(mic_map) == 4, f"Unexpected mic_input_channel_map shape: {mic_map}"
        expected_by_channel = {
            MIC_PASSTHROUGH_OUTPUT_BASE_CH + mic_idx: lane_pattern[
                int(mic_map[mic_idx])
            ]
            for mic_idx in range(4)
        }

        remote_wav = f"/tmp/sat1_spk_pattern_probe_{int(time.time())}.wav"
        try:
            await _set_mic_input_routing(
                ctrl_sess,
                hil_cli_cmd,
                mic_source_mode=I2S_INPUT_MODE_PACKAGED,
                mic_input_channel_map=mic_map,
            )
            await _set_mic_output_channels(ctrl_sess, hil_cli_cmd, 0, 3)
            await _set_mic_output_packing(
                ctrl_sess,
                hil_cli_cmd,
                enabled=True,
                upsample_channel_map=[0, 3, 4, 5, 6, 7],
            )

            with tempfile.TemporaryDirectory(prefix="sat1_spk_pattern_") as tmpdir:
                local_wav = Path(tmpdir) / "silence.wav"
                sample_count = settings["playback_s"] * I2S_RATE_HZ
                _write_stereo_wav_s32(local_wav, [0] * sample_count, [0] * sample_count)
                await play_sess.upload(local_wav, remote_path=remote_wav)

            left, right = await _record_play_and_read(
                play_sess,
                rec_sess,
                remote_wav=remote_wav,
                duration_s=float(settings["capture_s"]),
                arecord_dev=settings["arecord_dev"],
                aplay_args=aplay_args,
            )
            values_by_output_channel, left_phase_offset, right_phase_offset, _ = (
                _extract_packed_mic_outputs_phase_aligned(
                    left,
                    right,
                    expected_by_channel,
                )
            )

            failures: list[str] = []
            for channel, expected in expected_by_channel.items():
                values = values_by_output_channel[channel]
                assert values, f"No captured values for output channel {channel}"
                values = values[settings["packed_drop_samples"] :]
                matches = sum(1 for value in values if value == expected)
                match_ratio = matches / len(values)
                if match_ratio < settings["spk_pattern_min_match_ratio"]:
                    failures.append(
                        f"ch={channel} expected=0x{expected:08x} "
                        f"match_ratio={match_ratio:.3f} min_ratio={settings['spk_pattern_min_match_ratio']:.3f} "
                        f"phase_offset_l={left_phase_offset} phase_offset_r={right_phase_offset} preview={values[:12]}"
                    )

            if failures:
                print(
                    "Speaker-pattern propagation mismatches (diagnostic):\n"
                    + "\n".join(failures)
                )
        finally:
            await _set_mic_input_routing(
                ctrl_sess,
                hil_cli_cmd,
                mic_source_mode=int(original["mic_input"]["mic_source_mode"]),
                ref_source_mode=int(original["mic_input"]["ref_source_mode"]),
                mic_input_channel_map=list(
                    original["mic_input"]["mic_input_channel_map"]
                ),
                ref_input_channel_map=list(
                    original["mic_input"]["ref_input_channel_map"]
                ),
            )
            await _set_mic_output_channels(
                ctrl_sess,
                hil_cli_cmd,
                int(original["mic_output"]["i2s_channel_map"][0]),
                int(original["mic_output"]["i2s_channel_map"][1]),
            )
            await _set_mic_output_packing(
                ctrl_sess,
                hil_cli_cmd,
                enabled=bool(original["mic_output"]["pack_extra_upsample_channels"]),
                upsample_channel_map=list(
                    original["mic_output"]["upsample_channel_map"]
                ),
            )
            await play_sess.cmd(f"rm -f {remote_wav}", check=False)
