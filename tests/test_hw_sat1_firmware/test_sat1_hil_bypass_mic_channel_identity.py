import asyncio
import json
import math
import os
import shlex
import struct
import tempfile
import time
import wave
from collections import Counter
from contextlib import asynccontextmanager
from typing import AsyncIterator, cast
from pathlib import Path

import pytest

from hil_utils.ssh_helpers import RemoteAudioSession
from tests.conftest import PROJ_ROOT


I2S_RATE_HZ = 48000
PIPELINE_RATE_HZ = 16000
UPSAMPLE_FACTOR = I2S_RATE_HZ // PIPELINE_RATE_HZ
# frame_data_t channel order in fixed_delay pipeline:
# 0..1 processed, 2..3 references, 4..7 mic passthrough 0..3
MIC_PASSTHROUGH_OUTPUT_BASE_CH = 4
PACKAGED_SYNC_WORD = 0x7E57A55A

SAT1_HIL_BYPASS_EXPECT_FW_SUBSTR = os.getenv("SAT1_HIL_BYPASS_EXPECT_FW_SUBSTR", "")
SAT1_HIL_BYPASS_APLAY_DEV = os.getenv("SAT1_HIL_APLAY_DEV", "hw:0,0")
SAT1_HIL_BYPASS_ARECORD_DEV = os.getenv("SAT1_HIL_ARECORD_DEV", "hw:0,1")
SAT1_HIL_BYPASS_PLAYBACK_S = int(os.getenv("SAT1_HIL_BYPASS_PLAYBACK_S", "2"))
SAT1_HIL_BYPASS_CAPTURE_S = int(os.getenv("SAT1_HIL_BYPASS_CAPTURE_S", "1"))
SAT1_HIL_BYPASS_MIN_RATIO = float(os.getenv("SAT1_HIL_BYPASS_MIN_RATIO", "1.0"))
SAT1_HIL_BYPASS_SETTLE_S = float(os.getenv("SAT1_HIL_BYPASS_SETTLE_S", "0.1"))
SAT1_HIL_MIC_PATTERN_MIN_MATCH_RATIO = float(
    os.getenv("SAT1_HIL_MIC_PATTERN_MIN_MATCH_RATIO", "0.95")
)
SAT1_HIL_SPK_PATTERN_MIN_MATCH_RATIO = float(
    os.getenv("SAT1_HIL_SPK_PATTERN_MIN_MATCH_RATIO", "0.95")
)
SAT1_HIL_WAV_PATTERN_MIN_MATCH_RATIO = float(
    os.getenv("SAT1_HIL_WAV_PATTERN_MIN_MATCH_RATIO", "0.95")
)
SAT1_HIL_APLAY_STRICT_FLAGS = os.getenv("SAT1_HIL_APLAY_STRICT_FLAGS", "1") == "1"
SAT1_HIL_PACKED_DROP_SAMPLES = int(os.getenv("SAT1_HIL_PACKED_DROP_SAMPLES", "1600"))


def _aplay_args() -> list[str]:
    args = [f"-D{SAT1_HIL_BYPASS_APLAY_DEV}"]
    if SAT1_HIL_APLAY_STRICT_FLAGS:
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


async def _get_audio_settings(sess: RemoteAudioSession, sat1_rpi_sat1_cmd: str) -> dict:
    last_err = ""
    for _ in range(5):
        cmd = f"{sat1_rpi_sat1_cmd} xmos get-mic-pipeline-settings --json"
        out = await _run_cmd(sess, cmd)
        if out:
            return json.loads(out.splitlines()[-1])
        last_err = out
        await asyncio.sleep(0.3)
    raise AssertionError(last_err)


async def _set_mic_input_routing(
    sess: RemoteAudioSession,
    sat1_rpi_sat1_cmd: str,
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
    cmd = f"{sat1_rpi_sat1_cmd} xmos set-mic-pipeline-settings --json {shlex.quote(payload)}"
    out = await _run_cmd(sess, cmd)
    assert "True" in out


async def _set_mic_output_channels(
    sess: RemoteAudioSession, sat1_rpi_sat1_cmd: str, left: int, right: int
) -> None:
    payload = json.dumps(
        {"mic_output": {"i2s_channel_map": [int(left), int(right)]}},
        separators=(",", ":"),
    )
    cmd = f"{sat1_rpi_sat1_cmd} xmos set-mic-pipeline-settings --json {shlex.quote(payload)}"
    out = await _run_cmd(sess, cmd)
    assert "True" in out


async def _set_mic_output_packing(
    sess: RemoteAudioSession,
    sat1_rpi_sat1_cmd: str,
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
    cmd = f"{sat1_rpi_sat1_cmd} xmos set-mic-pipeline-settings --json {shlex.quote(payload)}"
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
        arecord_args=[f"-D{SAT1_HIL_BYPASS_ARECORD_DEV}", f"-d{duration_int}"],
    )
    await play_sess.start_play(
        remote_path=remote_wav,
        num_channels=2,
        aplay_args=_aplay_args(),
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


def _synthesize_one_hot_mics(
    active_mic_idx: int, frame_count_16k: int
) -> list[list[int]]:
    assert 0 <= active_mic_idx < 4
    pulse_amp = 240000000
    mics = [[0 for _ in range(frame_count_16k)] for _ in range(4)]
    for frame_start in range(0, frame_count_16k, 160):
        idx = frame_start + 40
        if idx < frame_count_16k:
            mics[active_mic_idx][idx] = pulse_amp
    return mics


def _pack_mics_to_stereo_48k(
    mic_frames_16k: list[list[int]], mic_input_channel_map: list[int]
) -> tuple[list[int], list[int]]:
    frame_count_16k = len(mic_frames_16k[0])
    frame_count_48k = frame_count_16k * UPSAMPLE_FACTOR
    left = [0 for _ in range(frame_count_48k)]
    right = [0 for _ in range(frame_count_48k)]

    for i in range(frame_count_16k):
        left[(i * UPSAMPLE_FACTOR) + 0] = PACKAGED_SYNC_WORD

    for mic_idx, lane in enumerate(mic_input_channel_map):
        channel = lane // 3
        phase = lane % 3
        assert channel in (0, 1)
        for i in range(frame_count_16k):
            out_idx = (i * UPSAMPLE_FACTOR) + phase
            if channel == 0:
                left[out_idx] = mic_frames_16k[mic_idx][i]
            else:
                right[out_idx] = mic_frames_16k[mic_idx][i]

    return left, right


def _write_lane_pattern_wav(
    path: Path,
    *,
    sample_count_16k: int,
    lane_pattern: dict[int, int],
) -> None:
    left = [0 for _ in range(sample_count_16k * UPSAMPLE_FACTOR)]
    right = [0 for _ in range(sample_count_16k * UPSAMPLE_FACTOR)]
    for frame in range(sample_count_16k):
        out = frame * UPSAMPLE_FACTOR
        left[out + 0] = int(lane_pattern[0])
        left[out + 1] = int(lane_pattern[1])
        left[out + 2] = int(lane_pattern[2])
        right[out + 0] = int(lane_pattern[3])
        right[out + 1] = int(lane_pattern[4])
        right[out + 2] = int(lane_pattern[5])
    _write_stereo_wav_s32(path, left, right)


def _most_common_value(values: list[int]) -> int:
    counts = Counter(values)
    return int(counts.most_common(1)[0][0])


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


def _extract_pipeline_lane(samples_48k: list[int], lane: int = 0) -> list[int]:
    assert UPSAMPLE_FACTOR == 3
    return samples_48k[lane::UPSAMPLE_FACTOR]


def _rms(values: list[int]) -> float:
    assert values, "Expected non-empty sample list"
    acc = 0
    for value in values:
        acc += value * value
    return math.sqrt(acc / len(values))


def _rms_for_pipeline_channel(samples_48k: list[int]) -> float:
    lane_rms = []
    for lane_idx in range(UPSAMPLE_FACTOR):
        lane = _extract_pipeline_lane(samples_48k, lane=lane_idx)
        lane_rms.append(_rms(lane))
    return max(lane_rms)


@pytest.mark.hil
@pytest.mark.sat1
@pytest.mark.requires_bypass_firmware
async def test_sat1_bypass_mic_channel_identity_packaged_injection(
    require_sat1_hil: None,
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
) -> None:
    async with _audio_sessions(sat1_rpi_host) as (ctrl_sess, play_sess, rec_sess):
        fw = await _run_cmd(
            ctrl_sess,
            f"{sat1_rpi_sat1_cmd} xmos read-firmware",
            timeout=30,
        )
        fw_text = fw.strip()
        assert fw_text, "Expected firmware identifier output"
        if SAT1_HIL_BYPASS_EXPECT_FW_SUBSTR:
            assert SAT1_HIL_BYPASS_EXPECT_FW_SUBSTR in fw_text, (
                "Expected bypass firmware variant to be active; "
                f"firmware={fw_text!r} expected_substr={SAT1_HIL_BYPASS_EXPECT_FW_SUBSTR!r}"
            )

        original = await _get_audio_settings(ctrl_sess, sat1_rpi_sat1_cmd)
        if int(original["available_mic_count"]) != 4:
            pytest.skip(
                f"Need 4 available mics for this test, got {original['available_mic_count']}"
            )

        mic_map = list(original["mic_input"]["mic_input_channel_map"])
        assert len(mic_map) == 4, f"Unexpected mic_input_channel_map shape: {mic_map}"

        remote_wavs: list[str] = []
        try:
            await _set_mic_input_routing(
                ctrl_sess,
                sat1_rpi_sat1_cmd,
                mic_source_mode=1,
                mic_input_channel_map=mic_map,
            )
            await _set_mic_output_packing(
                ctrl_sess,
                sat1_rpi_sat1_cmd,
                enabled=True,
                upsample_channel_map=[0, 3, 4, 5, 6, 7],
            )
            configured = await _get_audio_settings(ctrl_sess, sat1_rpi_sat1_cmd)
            assert int(configured["mic_input"]["mic_source_mode"]) == 1, configured
            assert [
                int(v) for v in configured["mic_input"]["mic_input_channel_map"]
            ] == [int(v) for v in mic_map], configured
            assert int(configured["mic_output"]["pack_extra_upsample_channels"]) == 1, (
                configured
            )
            assert [
                int(v) for v in configured["mic_output"]["upsample_channel_map"]
            ] == [
                0,
                3,
                4,
                5,
                6,
                7,
            ], configured
            await asyncio.sleep(SAT1_HIL_BYPASS_SETTLE_S)

            frame_count_16k = SAT1_HIL_BYPASS_PLAYBACK_S * PIPELINE_RATE_HZ
            ratios: list[float] = []
            low_signal_cases: list[str] = []
            for active_mic in range(4):
                mics = _synthesize_one_hot_mics(active_mic, frame_count_16k)
                left, right = _pack_mics_to_stereo_48k(mics, mic_map)
                with tempfile.TemporaryDirectory(
                    prefix="sat1_bypass_identity_"
                ) as tmpdir:
                    local_wav = Path(tmpdir) / f"bypass_mic_{active_mic}.wav"
                    _write_stereo_wav_s32(local_wav, left, right)
                    remote_wav = (
                        f"/tmp/sat1_bypass_identity_{int(time.time())}_{active_mic}.wav"
                    )
                    remote_wavs.append(remote_wav)
                    await play_sess.upload(local_wav, remote_path=remote_wav)

                expected_ch = MIC_PASSTHROUGH_OUTPUT_BASE_CH + active_mic
                rms_by_output_ch: dict[int, float] = {}
                for left_ch, right_ch in ((4, 5), (6, 7)):
                    await _set_mic_output_channels(
                        ctrl_sess, sat1_rpi_sat1_cmd, left_ch, right_ch
                    )
                    await asyncio.sleep(SAT1_HIL_BYPASS_SETTLE_S)
                    left_samples, right_samples = await _record_play_and_read(
                        play_sess,
                        rec_sess,
                        remote_wav=remote_wav,
                        duration_s=float(SAT1_HIL_BYPASS_CAPTURE_S),
                    )
                    rms_by_output_ch[left_ch] = _rms_for_pipeline_channel(left_samples)
                    rms_by_output_ch[right_ch] = _rms_for_pipeline_channel(
                        right_samples
                    )

                on_rms = rms_by_output_ch[expected_ch]
                other_rms = [
                    rms for ch, rms in rms_by_output_ch.items() if ch != expected_ch
                ]
                off_rms = max(other_rms) if other_rms else 0.0
                if max(rms_by_output_ch.values()) < 1.0:
                    low_signal_cases.append(
                        f"active_mic={active_mic} rms_by_output_ch={rms_by_output_ch}"
                    )
                    continue

                if off_rms <= 0.0:
                    low_signal_cases.append(
                        "active_mic={} expected_ch={} off_rms={} rms_by_output_ch={}".format(
                            active_mic,
                            expected_ch,
                            off_rms,
                            rms_by_output_ch,
                        )
                    )
                    continue

                ratio = on_rms / off_rms
                ratios.append(ratio)
                if ratio < SAT1_HIL_BYPASS_MIN_RATIO:
                    low_signal_cases.append(
                        "active_mic={} expected_ch={} on_rms={:.2f} max_other_rms={:.2f} "
                        "ratio={:.2f} min_ratio={:.2f}".format(
                            active_mic,
                            expected_ch,
                            on_rms,
                            off_rms,
                            ratio,
                            SAT1_HIL_BYPASS_MIN_RATIO,
                        )
                    )

            assert len(ratios) >= 1, (
                "No measurable packaged bypass signal observed for any active mic. "
                + "\n".join(low_signal_cases)
            )
        finally:
            await _set_mic_input_routing(
                ctrl_sess,
                sat1_rpi_sat1_cmd,
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
                sat1_rpi_sat1_cmd,
                int(original["mic_output"]["i2s_channel_map"][0]),
                int(original["mic_output"]["i2s_channel_map"][1]),
            )
            await _set_mic_output_packing(
                ctrl_sess,
                sat1_rpi_sat1_cmd,
                enabled=bool(original["mic_output"]["pack_extra_upsample_channels"]),
                upsample_channel_map=list(
                    original["mic_output"]["upsample_channel_map"]
                ),
            )
            for remote_wav in remote_wavs:
                await play_sess.cmd(f"rm -f {remote_wav}", check=False)


@pytest.mark.hil
@pytest.mark.sat1
@pytest.mark.requires_bypass_firmware
async def test_sat1_bypass_mic_pattern_visible_on_packed_output(
    require_sat1_hil: None,
    sat1_rpi_host: str,
    sat1_rpi_py_cmd: str,
    sat1_rpi_sat1_cmd: str,
) -> None:
    async with _audio_sessions(sat1_rpi_host) as (ctrl_sess, play_sess, rec_sess):
        original = await _get_audio_settings(ctrl_sess, sat1_rpi_sat1_cmd)
        expected_by_channel = {
            4: 0x11111111,
            5: 0x22222222,
            6: 0x33333333,
            7: 0x44444444,
        }

        remote_wav = f"/tmp/sat1_mic_pattern_probe_{int(time.time())}.wav"
        try:
            await _set_mic_output_channels(ctrl_sess, sat1_rpi_sat1_cmd, 0, 3)
            await _set_mic_output_packing(
                ctrl_sess,
                sat1_rpi_sat1_cmd,
                enabled=True,
                upsample_channel_map=[0, 3, 4, 5, 6, 7],
            )

            with tempfile.TemporaryDirectory(prefix="sat1_mic_pattern_") as tmpdir:
                local_wav = Path(tmpdir) / "silence.wav"
                sample_count = SAT1_HIL_BYPASS_PLAYBACK_S * I2S_RATE_HZ
                _write_stereo_wav_s32(local_wav, [0] * sample_count, [0] * sample_count)
                await play_sess.upload(local_wav, remote_path=remote_wav)

            left, right = await _record_play_and_read(
                play_sess,
                rec_sess,
                remote_wav=remote_wav,
                duration_s=float(SAT1_HIL_BYPASS_CAPTURE_S),
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
                values = values[SAT1_HIL_PACKED_DROP_SAMPLES:]
                matches = sum(1 for value in values if value == expected)
                match_ratio = matches / len(values)
                if match_ratio < SAT1_HIL_MIC_PATTERN_MIN_MATCH_RATIO:
                    preview = values[:12]
                    failures.append(
                        f"ch={channel} expected=0x{expected:08x} "
                        f"match_ratio={match_ratio:.3f} min_ratio={SAT1_HIL_MIC_PATTERN_MIN_MATCH_RATIO:.3f} "
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
                sat1_rpi_sat1_cmd,
                int(original["mic_output"]["i2s_channel_map"][0]),
                int(original["mic_output"]["i2s_channel_map"][1]),
            )
            await _set_mic_output_packing(
                ctrl_sess,
                sat1_rpi_sat1_cmd,
                enabled=bool(original["mic_output"]["pack_extra_upsample_channels"]),
                upsample_channel_map=list(
                    original["mic_output"]["upsample_channel_map"]
                ),
            )
            await play_sess.cmd(f"rm -f {remote_wav}", check=False)


@pytest.mark.hil
@pytest.mark.sat1
@pytest.mark.requires_bypass_firmware
async def test_sat1_speaker_pattern_propagates_to_raw_mic_outputs(
    require_sat1_hil: None,
    sat1_rpi_host: str,
    sat1_rpi_py_cmd: str,
    sat1_rpi_sat1_cmd: str,
) -> None:
    async with _audio_sessions(sat1_rpi_host) as (ctrl_sess, play_sess, rec_sess):
        lane_pattern = {
            0: 0x01010101,
            1: 0x02020202,
            2: 0x03030303,
            3: 0x04040404,
            4: 0x05050505,
            5: 0x06060606,
        }
        original = await _get_audio_settings(ctrl_sess, sat1_rpi_sat1_cmd)
        mic_map = list(original["mic_input"]["mic_input_channel_map"])
        assert len(mic_map) == 4, f"Unexpected mic_input_channel_map shape: {mic_map}"
        expected_by_channel = {
            4 + mic_idx: lane_pattern[int(mic_map[mic_idx])] for mic_idx in range(4)
        }

        remote_wav = f"/tmp/sat1_spk_pattern_probe_{int(time.time())}.wav"
        try:
            await _set_mic_input_routing(
                ctrl_sess,
                sat1_rpi_sat1_cmd,
                mic_source_mode=1,
                mic_input_channel_map=mic_map,
            )
            await _set_mic_output_channels(ctrl_sess, sat1_rpi_sat1_cmd, 0, 3)
            await _set_mic_output_packing(
                ctrl_sess,
                sat1_rpi_sat1_cmd,
                enabled=True,
                upsample_channel_map=[0, 3, 4, 5, 6, 7],
            )

            with tempfile.TemporaryDirectory(prefix="sat1_spk_pattern_") as tmpdir:
                local_wav = Path(tmpdir) / "silence.wav"
                sample_count = SAT1_HIL_BYPASS_PLAYBACK_S * I2S_RATE_HZ
                _write_stereo_wav_s32(local_wav, [0] * sample_count, [0] * sample_count)
                await play_sess.upload(local_wav, remote_path=remote_wav)

            left, right = await _record_play_and_read(
                play_sess,
                rec_sess,
                remote_wav=remote_wav,
                duration_s=float(SAT1_HIL_BYPASS_CAPTURE_S),
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
                values = values[SAT1_HIL_PACKED_DROP_SAMPLES:]
                matches = sum(1 for value in values if value == expected)
                match_ratio = matches / len(values)
                if match_ratio < SAT1_HIL_SPK_PATTERN_MIN_MATCH_RATIO:
                    failures.append(
                        f"ch={channel} expected=0x{expected:08x} "
                        f"match_ratio={match_ratio:.3f} min_ratio={SAT1_HIL_SPK_PATTERN_MIN_MATCH_RATIO:.3f} "
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
                sat1_rpi_sat1_cmd,
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
                sat1_rpi_sat1_cmd,
                int(original["mic_output"]["i2s_channel_map"][0]),
                int(original["mic_output"]["i2s_channel_map"][1]),
            )
            await _set_mic_output_packing(
                ctrl_sess,
                sat1_rpi_sat1_cmd,
                enabled=bool(original["mic_output"]["pack_extra_upsample_channels"]),
                upsample_channel_map=list(
                    original["mic_output"]["upsample_channel_map"]
                ),
            )
            await play_sess.cmd(f"rm -f {remote_wav}", check=False)


@pytest.mark.hil
@pytest.mark.sat1
@pytest.mark.requires_bypass_firmware
async def test_sat1_packaged_wav_lane_pattern_propagates_to_raw_mic_outputs(
    require_sat1_hil: None,
    sat1_rpi_host: str,
    sat1_rpi_py_cmd: str,
    sat1_rpi_sat1_cmd: str,
) -> None:
    async with _audio_sessions(sat1_rpi_host) as (ctrl_sess, play_sess, rec_sess):
        lane_pattern = {
            0: PACKAGED_SYNC_WORD,
            1: 0x22222222,
            2: 0x33333333,
            3: 0x44444444,
            4: 0x55555555,
            5: 0x66666666,
        }
        original = await _get_audio_settings(ctrl_sess, sat1_rpi_sat1_cmd)
        mic_map = list(original["mic_input"]["mic_input_channel_map"])
        assert len(mic_map) == 4, f"Unexpected mic_input_channel_map shape: {mic_map}"
        expected_by_output_channel = {
            4 + mic_idx: lane_pattern[int(mic_map[mic_idx])] for mic_idx in range(4)
        }

        remote_wav = f"/tmp/sat1_wav_pattern_probe_{int(time.time())}.wav"
        try:
            await _set_mic_input_routing(
                ctrl_sess,
                sat1_rpi_sat1_cmd,
                mic_source_mode=1,
                mic_input_channel_map=mic_map,
            )
            await _set_mic_output_channels(ctrl_sess, sat1_rpi_sat1_cmd, 0, 3)
            await _set_mic_output_packing(
                ctrl_sess,
                sat1_rpi_sat1_cmd,
                enabled=True,
                upsample_channel_map=[0, 3, 4, 5, 6, 7],
            )

            with tempfile.TemporaryDirectory(prefix="sat1_wav_pattern_") as tmpdir:
                local_wav = Path(tmpdir) / "wav_lane_pattern.wav"
                _write_lane_pattern_wav(
                    local_wav,
                    sample_count_16k=SAT1_HIL_BYPASS_PLAYBACK_S * PIPELINE_RATE_HZ,
                    lane_pattern=lane_pattern,
                )
                await play_sess.upload(local_wav, remote_path=remote_wav)

            left, right = await _record_play_and_read(
                play_sess,
                rec_sess,
                remote_wav=remote_wav,
                duration_s=float(SAT1_HIL_BYPASS_CAPTURE_S),
            )
            values_by_output_channel, left_phase_offset, right_phase_offset, _ = (
                _extract_packed_mic_outputs_phase_aligned(
                    left,
                    right,
                    expected_by_output_channel,
                )
            )

            failures: list[str] = []
            for channel, expected in expected_by_output_channel.items():
                values = values_by_output_channel[channel]
                assert values, f"No captured values for output channel {channel}"
                values = values[SAT1_HIL_PACKED_DROP_SAMPLES:]
                matches = sum(1 for value in values if value == expected)
                match_ratio = matches / len(values)
                if match_ratio < SAT1_HIL_WAV_PATTERN_MIN_MATCH_RATIO:
                    failures.append(
                        f"ch={channel} expected=0x{expected:08x} "
                        f"match_ratio={match_ratio:.3f} min_ratio={SAT1_HIL_WAV_PATTERN_MIN_MATCH_RATIO:.3f} "
                        f"phase_offset_l={left_phase_offset} phase_offset_r={right_phase_offset} preview={values[:12]}"
                    )

            if failures:
                print(
                    "WAV lane-pattern propagation mismatches (diagnostic):\n"
                    + "\n".join(failures)
                )
        finally:
            await _set_mic_input_routing(
                ctrl_sess,
                sat1_rpi_sat1_cmd,
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
                sat1_rpi_sat1_cmd,
                int(original["mic_output"]["i2s_channel_map"][0]),
                int(original["mic_output"]["i2s_channel_map"][1]),
            )
            await _set_mic_output_packing(
                ctrl_sess,
                sat1_rpi_sat1_cmd,
                enabled=bool(original["mic_output"]["pack_extra_upsample_channels"]),
                upsample_channel_map=list(
                    original["mic_output"]["upsample_channel_map"]
                ),
            )
            await play_sess.cmd(f"rm -f {remote_wav}", check=False)
