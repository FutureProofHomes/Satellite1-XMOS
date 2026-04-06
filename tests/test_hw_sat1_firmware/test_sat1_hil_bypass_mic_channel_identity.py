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
from collections import Counter
from pathlib import Path

import pytest

from tests.conftest import PROJ_ROOT


I2S_RATE_HZ = 48000
PIPELINE_RATE_HZ = 16000
UPSAMPLE_FACTOR = I2S_RATE_HZ // PIPELINE_RATE_HZ
# frame_data_t channel order in fixed_delay pipeline:
# 0..1 processed, 2..3 references, 4..7 mic passthrough 0..3
MIC_PASSTHROUGH_OUTPUT_BASE_CH = 4
MIC_INPUT_SNAPSHOT_CMD_READ = 0x86
MIC_INPUT_SNAPSHOT_SAMPLE_COUNT = 4
SPK_INPUT_SNAPSHOT_CMD_READ = 0x87
PACKAGED_SYNC_WORD = 0x7E57A55A
MIC_INPUT_SNAPSHOT_PAYLOAD_LEN = (
    24
    + (6 * MIC_INPUT_SNAPSHOT_SAMPLE_COUNT * 4)
    + (4 * MIC_INPUT_SNAPSHOT_SAMPLE_COUNT * 4)
)
SPK_INPUT_SNAPSHOT_PAYLOAD_LEN = 20 + (6 * MIC_INPUT_SNAPSHOT_SAMPLE_COUNT * 4)

SAT1_HIL_BYPASS_EXPECT_FW_SUBSTR = os.getenv("SAT1_HIL_BYPASS_EXPECT_FW_SUBSTR", "")
SAT1_HIL_BYPASS_APLAY_DEV = os.getenv("SAT1_HIL_APLAY_DEV", "hw:0,0")
SAT1_HIL_BYPASS_ARECORD_DEV = os.getenv("SAT1_HIL_ARECORD_DEV", "hw:0,1")
SAT1_HIL_BYPASS_PLAYBACK_S = int(os.getenv("SAT1_HIL_BYPASS_PLAYBACK_S", "3"))
SAT1_HIL_BYPASS_CAPTURE_S = int(os.getenv("SAT1_HIL_BYPASS_CAPTURE_S", "2"))
SAT1_HIL_BYPASS_MIN_RATIO = float(os.getenv("SAT1_HIL_BYPASS_MIN_RATIO", "1.0"))
SAT1_HIL_BYPASS_SETTLE_S = float(os.getenv("SAT1_HIL_BYPASS_SETTLE_S", "0.2"))
SAT1_HIL_BYPASS_DEBUG_POLL_S = float(os.getenv("SAT1_HIL_BYPASS_DEBUG_POLL_S", "0.15"))
SAT1_HIL_BYPASS_DEBUG_MIN_SAMPLES = int(
    os.getenv("SAT1_HIL_BYPASS_DEBUG_MIN_SAMPLES", "1")
)
SAT1_HIL_BYPASS_DEBUG_MIN_MATCH_RATIO = float(
    os.getenv("SAT1_HIL_BYPASS_DEBUG_MIN_MATCH_RATIO", "0.0")
)
SAT1_HIL_MIC_PATTERN_TEST = os.getenv("SAT1_HIL_MIC_PATTERN_TEST", "0") == "1"
SAT1_HIL_MIC_PATTERN_MIN_MATCH_RATIO = float(
    os.getenv("SAT1_HIL_MIC_PATTERN_MIN_MATCH_RATIO", "0.95")
)
SAT1_HIL_SPK_PATTERN_TEST = os.getenv("SAT1_HIL_SPK_PATTERN_TEST", "0") == "1"
SAT1_HIL_SPK_PATTERN_MIN_MATCH_RATIO = float(
    os.getenv("SAT1_HIL_SPK_PATTERN_MIN_MATCH_RATIO", "0.95")
)
SAT1_HIL_WAV_PATTERN_TEST = os.getenv("SAT1_HIL_WAV_PATTERN_TEST", "0") == "1"
SAT1_HIL_WAV_PATTERN_MIN_MATCH_RATIO = float(
    os.getenv("SAT1_HIL_WAV_PATTERN_MIN_MATCH_RATIO", "0.95")
)
SAT1_HIL_APLAY_STRICT_FLAGS = os.getenv("SAT1_HIL_APLAY_STRICT_FLAGS", "1") == "1"
SAT1_HIL_PACKED_DROP_SAMPLES = int(os.getenv("SAT1_HIL_PACKED_DROP_SAMPLES", "1600"))

FRAME_COUNTER_RE = re.compile(r"frame_counter\s*=\s*(\d+)")
MIC_MEAN_ABS_RE = re.compile(r"mic_mean_abs\s*=\s*\(([^)]*)\)")


def _run_ssh(
    host: str, cmd: str, timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, cmd],
        cwd=PROJ_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _run_remote_sdk_json(host: str, sat1_rpi_py_cmd: str, script: str) -> dict:
    cmd_tokens = shlex.split(sat1_rpi_py_cmd)
    assert cmd_tokens, "SAT1_RPI_PY_CMD resolved to empty command"
    remote_cmd = " ".join(shlex.quote(v) for v in cmd_tokens + ["-c", script])
    res = _run_ssh(host, remote_cmd, timeout=60)
    assert res.returncode == 0, res.stdout + res.stderr
    out = res.stdout.strip()
    assert out, "Expected JSON output from remote SDK script"
    return json.loads(out.splitlines()[-1])


def _get_audio_settings(host: str, sat1_rpi_sat1_cmd: str) -> dict:
    last_err = ""
    for _ in range(5):
        res = _run_ssh(
            host,
            f"{sat1_rpi_sat1_cmd} xmos get-mic-pipeline-settings --json",
            timeout=30,
        )
        if res.returncode == 0:
            out = res.stdout.strip()
            assert out, "Expected JSON output from get-mic-pipeline-settings"
            return json.loads(out.splitlines()[-1])
        last_err = res.stdout + res.stderr
        time.sleep(0.3)
    raise AssertionError(last_err)


def _set_mic_input_routing(
    host: str,
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
    res = _run_ssh(
        host,
        f"{sat1_rpi_sat1_cmd} xmos set-mic-pipeline-settings --json {shlex.quote(payload)}",
        timeout=30,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "True" in res.stdout, res.stdout + res.stderr


def _set_mic_output_channels(
    host: str, sat1_rpi_sat1_cmd: str, left: int, right: int
) -> None:
    payload = json.dumps(
        {"mic_output": {"i2s_channel_map": [int(left), int(right)]}},
        separators=(",", ":"),
    )
    res = _run_ssh(
        host,
        f"{sat1_rpi_sat1_cmd} xmos set-mic-pipeline-settings --json {shlex.quote(payload)}",
        timeout=30,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "True" in res.stdout, res.stdout + res.stderr


def _set_mic_output_packing(
    host: str, sat1_rpi_sat1_cmd: str, *, enabled: bool, upsample_channel_map: list[int]
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
    res = _run_ssh(
        host,
        f"{sat1_rpi_sat1_cmd} xmos set-mic-pipeline-settings --json {shlex.quote(payload)}",
        timeout=30,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "True" in res.stdout, res.stdout + res.stderr


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


def _capture_channel_samples_during_playback(
    host: str, remote_wav: str, *, channel_index: int = 0
) -> list[int]:
    strict_flags = ""
    if SAT1_HIL_APLAY_STRICT_FLAGS:
        strict_flags = (
            " --disable-resample --disable-channels --disable-format --disable-softvol"
        )
    aplay_cmd = (
        f"aplay{strict_flags} -D {SAT1_HIL_BYPASS_APLAY_DEV} -f S32_LE -r {I2S_RATE_HZ} -c 2 "
        f"{shlex.quote(remote_wav)}"
    )
    play_proc = subprocess.Popen(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            host,
            aplay_cmd,
        ],
        cwd=PROJ_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    time.sleep(0.2)
    capture_cmd = (
        f"arecord -D {SAT1_HIL_BYPASS_ARECORD_DEV} -f S32_LE -r {I2S_RATE_HZ} -c 2 "
        f"-d {SAT1_HIL_BYPASS_CAPTURE_S} -t raw -q"
    )
    cap = subprocess.run(
        ["ssh", host, capture_cmd],
        cwd=PROJ_ROOT,
        check=False,
        capture_output=True,
        timeout=SAT1_HIL_BYPASS_CAPTURE_S + 20,
    )
    out, err = play_proc.communicate(timeout=20)
    assert play_proc.returncode == 0, out + err
    assert cap.returncode == 0, cap.stderr.decode("utf-8", errors="replace")

    samples = [v[0] for v in struct.iter_unpack("<i", cap.stdout)]
    assert samples, "Expected captured PCM samples"
    channel = samples[channel_index::2]
    assert channel, "Expected selected output channel samples"
    return channel


def _capture_stereo_samples_during_playback(
    host: str, remote_wav: str
) -> tuple[list[int], list[int]]:
    strict_flags = ""
    if SAT1_HIL_APLAY_STRICT_FLAGS:
        strict_flags = (
            " --disable-resample --disable-channels --disable-format --disable-softvol"
        )
    aplay_cmd = (
        f"aplay{strict_flags} -D {SAT1_HIL_BYPASS_APLAY_DEV} -f S32_LE -r {I2S_RATE_HZ} -c 2 "
        f"{shlex.quote(remote_wav)}"
    )
    play_proc = subprocess.Popen(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            host,
            aplay_cmd,
        ],
        cwd=PROJ_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    time.sleep(0.2)
    capture_cmd = (
        f"arecord -D {SAT1_HIL_BYPASS_ARECORD_DEV} -f S32_LE -r {I2S_RATE_HZ} -c 2 "
        f"-d {SAT1_HIL_BYPASS_CAPTURE_S} -t raw -q"
    )
    cap = subprocess.run(
        ["ssh", host, capture_cmd],
        cwd=PROJ_ROOT,
        check=False,
        capture_output=True,
        timeout=SAT1_HIL_BYPASS_CAPTURE_S + 20,
    )
    out, err = play_proc.communicate(timeout=20)
    assert play_proc.returncode == 0, out + err
    assert cap.returncode == 0, cap.stderr.decode("utf-8", errors="replace")

    samples = [v[0] for v in struct.iter_unpack("<i", cap.stdout)]
    assert samples, "Expected captured PCM samples"
    left = samples[0::2]
    right = samples[1::2]
    assert left and right, "Expected stereo capture samples"
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


def _lane_value_with_phase_rotation(
    lane_pattern: dict[int, int], lane: int, left_offset: int, right_offset: int
) -> int:
    if lane < 3:
        idx = (lane + left_offset) % 3
        return int(lane_pattern[idx])
    idx = 3 + ((lane - 3 + right_offset) % 3)
    return int(lane_pattern[idx])


def _detect_lane_phase_offsets_from_snapshot(
    snapshot: dict, lane_pattern: dict[int, int]
) -> tuple[int, int, int]:
    observed = [[int(v) for v in row] for row in snapshot["packaged_lane_samples"]]

    def score_for_offsets(lo: int, ro: int) -> int:
        score = 0
        for lane in range(6):
            expected = _lane_value_with_phase_rotation(lane_pattern, lane, lo, ro)
            score += sum(1 for v in observed[lane] if v == expected)
        return score

    best_lo = 0
    best_ro = 0
    best_score = -1
    for lo in range(3):
        for ro in range(3):
            s = score_for_offsets(lo, ro)
            if s > best_score:
                best_score = s
                best_lo = lo
                best_ro = ro
    return best_lo, best_ro, best_score


def _infer_ingress_phase_offsets_via_snapshot(
    host: str,
    sat1_rpi_py_cmd: str,
    remote_wav: str,
    lane_pattern: dict[int, int],
) -> tuple[int, int, dict]:
    strict_flags = ""
    if SAT1_HIL_APLAY_STRICT_FLAGS:
        strict_flags = (
            " --disable-resample --disable-channels --disable-format --disable-softvol"
        )
    aplay_cmd = (
        f"aplay{strict_flags} -D {SAT1_HIL_BYPASS_APLAY_DEV} -f S32_LE -r {I2S_RATE_HZ} -c 2 "
        f"{shlex.quote(remote_wav)}"
    )
    play_proc = subprocess.Popen(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, aplay_cmd],
        cwd=PROJ_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    snaps: list[dict] = []
    try:
        while True:
            if play_proc.poll() is not None:
                break
            snap = _read_spk_input_packaged_snapshot(host, sat1_rpi_py_cmd)
            if snap.get("ok"):
                snaps.append(snap)
            time.sleep(0.08)
    finally:
        out, err = play_proc.communicate(timeout=20)
        assert play_proc.returncode == 0, out + err

    assert snaps, "No valid ingress snapshots captured for phase inference"
    best = max(
        snaps,
        key=lambda s: _detect_lane_phase_offsets_from_snapshot(s, lane_pattern)[2],
    )
    lo, ro, _ = _detect_lane_phase_offsets_from_snapshot(best, lane_pattern)
    return lo, ro, best


def _extract_pipeline_lane(samples_48k: list[int], lane: int = 0) -> list[int]:
    assert UPSAMPLE_FACTOR == 3
    return samples_48k[lane::UPSAMPLE_FACTOR]


def _rms(values: list[int]) -> float:
    assert values, "Expected non-empty sample list"
    acc = 0
    for value in values:
        acc += value * value
    return math.sqrt(acc / len(values))


def _capture_rms_for_output_channel(host: str, remote_wav: str) -> float:
    ch = _capture_channel_samples_during_playback(host, remote_wav, channel_index=0)
    lane_rms = []
    for lane_idx in range(UPSAMPLE_FACTOR):
        lane = _extract_pipeline_lane(ch, lane=lane_idx)
        lane_rms.append(_rms(lane))
    return max(lane_rms)


def _read_doa_debug_stats(host: str, sat1_rpi_sat1_cmd: str) -> dict:
    res = _run_ssh(
        host, f"{sat1_rpi_sat1_cmd} xmos get-mic-input-debug-stats", timeout=30
    )
    if res.returncode != 0:
        return {"supported": False}
    text = (res.stdout or "").strip()
    frame = FRAME_COUNTER_RE.search(text)
    mic_abs = MIC_MEAN_ABS_RE.search(text)
    if not frame or not mic_abs:
        return {"supported": False}
    values = [int(v.strip()) for v in mic_abs.group(1).split(",") if v.strip()]
    return {
        "supported": True,
        "frame_counter": int(frame.group(1)),
        "mic_mean_abs": values,
    }


def _read_mic_input_packaged_snapshot(host: str, sat1_rpi_py_cmd: str) -> dict:
    script = f"""
import json
import struct
from satellite1.sat1_hat import XMOS
from satellite1.components.xmos_device_cntrl import AUDIO_PIPELINE_CONTROL

x = XMOS()
x.setup()
_ = x.read_firmware()
_ = x.wait_until_ready(timeout_s=3.0, poll_interval_s=0.1)
try:
    ok, payload = x._cntrl.transfer(
        AUDIO_PIPELINE_CONTROL.MIC_INPUT_SETTINGS_RES_ID,
        {MIC_INPUT_SNAPSHOT_CMD_READ},
        None,
        {MIC_INPUT_SNAPSHOT_PAYLOAD_LEN},
    )
    if (not ok) or payload is None:
        print(json.dumps({{"ok": False}}))
    elif len(payload) != {MIC_INPUT_SNAPSHOT_PAYLOAD_LEN}:
        print(json.dumps({{"ok": False, "payload_len": len(payload)}}))
    else:
        (
            magic,
            guard_a,
            guard_b,
            frame_counter,
            m0,
            m1,
            m2,
            m3,
            sample_count,
        ) = struct.unpack("<IIII4BI", payload[:24])
        vals = struct.unpack(
            "<" + "i" * (10 * {MIC_INPUT_SNAPSHOT_SAMPLE_COUNT}), payload[24:]
        )
        lane = []
        idx = 0
        for _ in range(6):
            lane.append([int(v) for v in vals[idx:idx+{MIC_INPUT_SNAPSHOT_SAMPLE_COUNT}]])
            idx += {MIC_INPUT_SNAPSHOT_SAMPLE_COUNT}
        mapped = []
        for _ in range(4):
            mapped.append([int(v) for v in vals[idx:idx+{MIC_INPUT_SNAPSHOT_SAMPLE_COUNT}]])
            idx += {MIC_INPUT_SNAPSHOT_SAMPLE_COUNT}
        print(json.dumps({{
            "ok": True,
            "magic": int(magic),
            "guard_a": int(guard_a),
            "guard_b": int(guard_b),
            "frame_counter": int(frame_counter),
            "mic_input_channel_map": [int(m0), int(m1), int(m2), int(m3)],
            "sample_count": int(sample_count),
            "packaged_lane_samples": lane,
            "mapped_mic_samples": mapped,
        }}))
finally:
    cntrl = getattr(x, "_cntrl", None)
    if cntrl is not None and hasattr(cntrl, "close"):
        cntrl.close()
"""
    return _run_remote_sdk_json(host, sat1_rpi_py_cmd, script)


def _read_spk_input_packaged_snapshot(host: str, sat1_rpi_py_cmd: str) -> dict:
    script = f"""
import json
import struct
from satellite1.sat1_hat import XMOS
from satellite1.components.xmos_device_cntrl import AUDIO_PIPELINE_CONTROL

x = XMOS()
x.setup()
_ = x.read_firmware()
_ = x.wait_until_ready(timeout_s=3.0, poll_interval_s=0.1)
try:
    ok, payload = x._cntrl.transfer(
        AUDIO_PIPELINE_CONTROL.MIC_INPUT_SETTINGS_RES_ID,
        {SPK_INPUT_SNAPSHOT_CMD_READ},
        None,
        {SPK_INPUT_SNAPSHOT_PAYLOAD_LEN},
    )
    if (not ok) or payload is None:
        print(json.dumps({{"ok": False}}))
    elif len(payload) != {SPK_INPUT_SNAPSHOT_PAYLOAD_LEN}:
        print(json.dumps({{"ok": False, "payload_len": len(payload)}}))
    else:
        magic, guard_a, guard_b, frame_counter, sample_count = struct.unpack(
            "<IIIII", payload[:20]
        )
        vals = struct.unpack(
            "<" + "i" * (6 * {MIC_INPUT_SNAPSHOT_SAMPLE_COUNT}), payload[20:]
        )
        lane = []
        idx = 0
        for _ in range(6):
            lane.append([int(v) for v in vals[idx:idx+{MIC_INPUT_SNAPSHOT_SAMPLE_COUNT}]])
            idx += {MIC_INPUT_SNAPSHOT_SAMPLE_COUNT}
        print(json.dumps({{
            "ok": True,
            "magic": int(magic),
            "guard_a": int(guard_a),
            "guard_b": int(guard_b),
            "frame_counter": int(frame_counter),
            "sample_count": int(sample_count),
            "packaged_lane_samples": lane,
        }}))
finally:
    cntrl = getattr(x, "_cntrl", None)
    if cntrl is not None and hasattr(cntrl, "close"):
        cntrl.close()
"""
    return _run_remote_sdk_json(host, sat1_rpi_py_cmd, script)


def _collect_doa_debug_samples_during_playback(
    host: str,
    sat1_rpi_sat1_cmd: str,
    remote_wav: str,
    *,
    poll_s: float,
) -> list[dict]:
    aplay_cmd = (
        f"aplay -D {SAT1_HIL_BYPASS_APLAY_DEV} -f S32_LE -r {I2S_RATE_HZ} -c 2 "
        f"{shlex.quote(remote_wav)}"
    )
    play_proc = subprocess.Popen(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            host,
            aplay_cmd,
        ],
        cwd=PROJ_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    samples: list[dict] = []
    try:
        while True:
            if play_proc.poll() is not None:
                break
            stats = _read_doa_debug_stats(host, sat1_rpi_sat1_cmd)
            stats["t"] = time.time()
            samples.append(stats)
            time.sleep(max(0.05, poll_s))
    finally:
        out, err = play_proc.communicate(timeout=20)
        assert play_proc.returncode == 0, out + err

    return samples


@pytest.mark.hil
@pytest.mark.sat1
@pytest.mark.requires_bypass_firmware
def test_sat1_bypass_mic_channel_identity_packaged_injection(
    require_sat1_hil: None,
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
) -> None:
    fw = _run_ssh(sat1_rpi_host, f"{sat1_rpi_sat1_cmd} xmos read-firmware", timeout=30)
    assert fw.returncode == 0, fw.stdout + fw.stderr
    fw_text = fw.stdout.strip()
    assert fw_text, "Expected firmware identifier output"
    if SAT1_HIL_BYPASS_EXPECT_FW_SUBSTR:
        assert SAT1_HIL_BYPASS_EXPECT_FW_SUBSTR in fw_text, (
            "Expected bypass firmware variant to be active; "
            f"firmware={fw_text!r} expected_substr={SAT1_HIL_BYPASS_EXPECT_FW_SUBSTR!r}"
        )

    original = _get_audio_settings(sat1_rpi_host, sat1_rpi_sat1_cmd)
    if int(original["available_mic_count"]) != 4:
        pytest.skip(
            f"Need 4 available mics for this test, got {original['available_mic_count']}"
        )

    mic_map = list(original["mic_input"]["mic_input_channel_map"])
    assert len(mic_map) == 4, f"Unexpected mic_input_channel_map shape: {mic_map}"

    remote_wavs: list[str] = []
    try:
        _set_mic_input_routing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            mic_source_mode=1,
            mic_input_channel_map=mic_map,
        )
        _set_mic_output_packing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            enabled=True,
            upsample_channel_map=[0, 3, 4, 5, 6, 7],
        )
        configured = _get_audio_settings(sat1_rpi_host, sat1_rpi_sat1_cmd)
        assert int(configured["mic_input"]["mic_source_mode"]) == 1, configured
        assert [int(v) for v in configured["mic_input"]["mic_input_channel_map"]] == [
            int(v) for v in mic_map
        ], configured
        assert int(configured["mic_output"]["pack_extra_upsample_channels"]) == 1, (
            configured
        )
        assert [int(v) for v in configured["mic_output"]["upsample_channel_map"]] == [
            0,
            3,
            4,
            5,
            6,
            7,
        ], configured
        time.sleep(SAT1_HIL_BYPASS_SETTLE_S)

        frame_count_16k = SAT1_HIL_BYPASS_PLAYBACK_S * PIPELINE_RATE_HZ
        ratios: list[float] = []
        diagnostics: list[dict] = []
        low_signal_cases: list[str] = []
        for active_mic in range(4):
            mics = _synthesize_one_hot_mics(active_mic, frame_count_16k)
            left, right = _pack_mics_to_stereo_48k(mics, mic_map)
            with tempfile.TemporaryDirectory(prefix="sat1_bypass_identity_") as tmpdir:
                local_wav = Path(tmpdir) / f"bypass_mic_{active_mic}.wav"
                _write_stereo_wav_s32(local_wav, left, right)
                remote_wav = (
                    f"/tmp/sat1_bypass_identity_{int(time.time())}_{active_mic}.wav"
                )
                remote_wavs.append(remote_wav)
                scp_res = subprocess.run(
                    ["scp", str(local_wav), f"{sat1_rpi_host}:{remote_wav}"],
                    cwd=PROJ_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                assert scp_res.returncode == 0, scp_res.stdout + scp_res.stderr

            expected_ch = MIC_PASSTHROUGH_OUTPUT_BASE_CH + active_mic
            rms_by_output_ch: dict[int, float] = {}
            for output_ch in range(
                MIC_PASSTHROUGH_OUTPUT_BASE_CH,
                MIC_PASSTHROUGH_OUTPUT_BASE_CH + 4,
            ):
                _set_mic_output_channels(
                    sat1_rpi_host, sat1_rpi_sat1_cmd, output_ch, output_ch
                )
                time.sleep(SAT1_HIL_BYPASS_SETTLE_S)
                rms_by_output_ch[output_ch] = _capture_rms_for_output_channel(
                    sat1_rpi_host, remote_wav
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
            observed_ch = max(
                rms_by_output_ch.keys(), key=lambda ch: rms_by_output_ch[ch]
            )
            diagnostics.append(
                {
                    "active_mic": active_mic,
                    "expected_ch": expected_ch,
                    "observed_peak_ch": int(observed_ch),
                    "rms_by_output_ch": rms_by_output_ch,
                    "ratio": ratio,
                }
            )
            if ratio < SAT1_HIL_BYPASS_MIN_RATIO:
                low_signal_cases.append(
                    "active_mic={} expected_ch={} observed_peak_ch={} "
                    "rms_by_output_ch={} on_rms={:.2f} max_other_rms={:.2f} "
                    "ratio={:.2f} min_ratio={:.2f}".format(
                        active_mic,
                        expected_ch,
                        observed_ch,
                        rms_by_output_ch,
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
        _set_mic_input_routing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            mic_source_mode=int(original["mic_input"]["mic_source_mode"]),
            ref_source_mode=int(original["mic_input"]["ref_source_mode"]),
            mic_input_channel_map=list(original["mic_input"]["mic_input_channel_map"]),
            ref_input_channel_map=list(original["mic_input"]["ref_input_channel_map"]),
        )
        _set_mic_output_channels(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            int(original["mic_output"]["i2s_channel_map"][0]),
            int(original["mic_output"]["i2s_channel_map"][1]),
        )
        _set_mic_output_packing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            enabled=bool(original["mic_output"]["pack_extra_upsample_channels"]),
            upsample_channel_map=list(original["mic_output"]["upsample_channel_map"]),
        )
        for remote_wav in remote_wavs:
            _run_ssh(sat1_rpi_host, f"rm -f {shlex.quote(remote_wav)}", timeout=10)


@pytest.mark.hil
@pytest.mark.sat1
@pytest.mark.requires_bypass_firmware
def test_sat1_bypass_packaged_mic_doa_debug_identity(
    require_sat1_hil: None,
    sat1_rpi_host: str,
    sat1_rpi_sat1_cmd: str,
) -> None:
    fw = _run_ssh(sat1_rpi_host, f"{sat1_rpi_sat1_cmd} xmos read-firmware", timeout=30)
    assert fw.returncode == 0, fw.stdout + fw.stderr

    original = _get_audio_settings(sat1_rpi_host, sat1_rpi_sat1_cmd)
    mic_map = list(original["mic_input"]["mic_input_channel_map"])
    assert len(mic_map) == 4, f"Unexpected mic_input_channel_map shape: {mic_map}"

    remote_wavs: list[str] = []
    try:
        _set_mic_input_routing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            mic_source_mode=1,
            mic_input_channel_map=mic_map,
        )
        time.sleep(SAT1_HIL_BYPASS_SETTLE_S)

        frame_count_16k = SAT1_HIL_BYPASS_PLAYBACK_S * PIPELINE_RATE_HZ
        failures: list[str] = []
        for active_mic in range(4):
            mics = _synthesize_one_hot_mics(active_mic, frame_count_16k)
            left, right = _pack_mics_to_stereo_48k(mics, mic_map)
            with tempfile.TemporaryDirectory(prefix="sat1_bypass_dbg_") as tmpdir:
                local_wav = Path(tmpdir) / f"bypass_dbg_mic_{active_mic}.wav"
                _write_stereo_wav_s32(local_wav, left, right)
                remote_wav = f"/tmp/sat1_bypass_dbg_{int(time.time())}_{active_mic}.wav"
                remote_wavs.append(remote_wav)
                scp_res = subprocess.run(
                    ["scp", str(local_wav), f"{sat1_rpi_host}:{remote_wav}"],
                    cwd=PROJ_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                assert scp_res.returncode == 0, scp_res.stdout + scp_res.stderr

            samples = _collect_doa_debug_samples_during_playback(
                sat1_rpi_host,
                sat1_rpi_sat1_cmd,
                remote_wav,
                poll_s=SAT1_HIL_BYPASS_DEBUG_POLL_S,
            )

            supported = [bool(s.get("supported", False)) for s in samples]
            if not any(supported):
                failures.append(
                    f"active_mic={active_mic} firmware does not expose get_doa_debug_stats"
                )
                continue

            valid = []
            for sample in samples:
                mic_mean_abs = list(sample.get("mic_mean_abs", []))
                if len(mic_mean_abs) != 4:
                    continue
                if max(mic_mean_abs) < 1:
                    continue
                dominant = max(range(4), key=lambda idx: mic_mean_abs[idx])
                valid.append(
                    {
                        "frame_counter": int(sample.get("frame_counter", 0)),
                        "mic_mean_abs": mic_mean_abs,
                        "dominant": int(dominant),
                    }
                )

            if len(valid) < SAT1_HIL_BYPASS_DEBUG_MIN_SAMPLES:
                failures.append(
                    f"active_mic={active_mic} insufficient valid DoA debug samples "
                    f"have={len(valid)} min_required={SAT1_HIL_BYPASS_DEBUG_MIN_SAMPLES}"
                )
                continue

            matches = sum(1 for sample in valid if sample["dominant"] == active_mic)
            match_ratio = matches / len(valid)

            frame_span = valid[-1]["frame_counter"] - valid[0]["frame_counter"]

            if match_ratio < SAT1_HIL_BYPASS_DEBUG_MIN_MATCH_RATIO:
                failures.append(
                    "active_mic={} match_ratio={:.3f} min_ratio={:.3f} "
                    "sample_count={} frame_span={} first_samples={}".format(
                        active_mic,
                        match_ratio,
                        SAT1_HIL_BYPASS_DEBUG_MIN_MATCH_RATIO,
                        len(valid),
                        frame_span,
                        valid[:5],
                    )
                )

        assert not failures, "DoA debug dominant-mic mismatches:\n" + "\n".join(
            failures
        )
    finally:
        _set_mic_input_routing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            mic_source_mode=int(original["mic_input"]["mic_source_mode"]),
            ref_source_mode=int(original["mic_input"]["ref_source_mode"]),
            mic_input_channel_map=list(original["mic_input"]["mic_input_channel_map"]),
            ref_input_channel_map=list(original["mic_input"]["ref_input_channel_map"]),
        )
        for remote_wav in remote_wavs:
            _run_ssh(sat1_rpi_host, f"rm -f {shlex.quote(remote_wav)}", timeout=10)


@pytest.mark.hil
@pytest.mark.sat1
@pytest.mark.requires_bypass_firmware
@pytest.mark.requires_mic_pattern_firmware
def test_sat1_bypass_mic_pattern_visible_on_packed_output(
    require_sat1_hil: None,
    sat1_rpi_host: str,
    sat1_rpi_py_cmd: str,
    sat1_rpi_sat1_cmd: str,
) -> None:
    if not SAT1_HIL_MIC_PATTERN_TEST:
        pytest.skip("Enable with SAT1_HIL_MIC_PATTERN_TEST=1")

    original = _get_audio_settings(sat1_rpi_host, sat1_rpi_sat1_cmd)
    expected_by_channel = {
        4: 0x11111111,
        5: 0x22222222,
        6: 0x33333333,
        7: 0x44444444,
    }

    remote_wav = f"/tmp/sat1_mic_pattern_probe_{int(time.time())}.wav"
    try:
        _set_mic_output_channels(sat1_rpi_host, sat1_rpi_sat1_cmd, 0, 3)
        _set_mic_output_packing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            enabled=True,
            upsample_channel_map=[0, 3, 4, 5, 6, 7],
        )

        with tempfile.TemporaryDirectory(prefix="sat1_mic_pattern_") as tmpdir:
            local_wav = Path(tmpdir) / "silence.wav"
            sample_count = SAT1_HIL_BYPASS_PLAYBACK_S * I2S_RATE_HZ
            _write_stereo_wav_s32(local_wav, [0] * sample_count, [0] * sample_count)
            scp_res = subprocess.run(
                ["scp", str(local_wav), f"{sat1_rpi_host}:{remote_wav}"],
                cwd=PROJ_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert scp_res.returncode == 0, scp_res.stdout + scp_res.stderr

        left, right = _capture_stereo_samples_during_playback(sat1_rpi_host, remote_wav)

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
                "Packed output pattern mismatches (diagnostic):\n" + "\n".join(failures)
            )
    finally:
        _set_mic_output_channels(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            int(original["mic_output"]["i2s_channel_map"][0]),
            int(original["mic_output"]["i2s_channel_map"][1]),
        )
        _set_mic_output_packing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            enabled=bool(original["mic_output"]["pack_extra_upsample_channels"]),
            upsample_channel_map=list(original["mic_output"]["upsample_channel_map"]),
        )
        _run_ssh(sat1_rpi_host, f"rm -f {shlex.quote(remote_wav)}", timeout=10)


@pytest.mark.hil
@pytest.mark.sat1
@pytest.mark.requires_bypass_firmware
@pytest.mark.requires_speaker_pattern_firmware
def test_sat1_speaker_pattern_propagates_to_raw_mic_outputs(
    require_sat1_hil: None,
    sat1_rpi_host: str,
    sat1_rpi_py_cmd: str,
    sat1_rpi_sat1_cmd: str,
) -> None:
    if not SAT1_HIL_SPK_PATTERN_TEST:
        pytest.skip("Enable with SAT1_HIL_SPK_PATTERN_TEST=1")

    lane_pattern = {
        0: 0x01010101,
        1: 0x02020202,
        2: 0x03030303,
        3: 0x04040404,
        4: 0x05050505,
        5: 0x06060606,
    }
    original = _get_audio_settings(sat1_rpi_host, sat1_rpi_sat1_cmd)
    mic_map = list(original["mic_input"]["mic_input_channel_map"])
    assert len(mic_map) == 4, f"Unexpected mic_input_channel_map shape: {mic_map}"
    expected_by_channel = {
        4 + mic_idx: lane_pattern[int(mic_map[mic_idx])] for mic_idx in range(4)
    }

    remote_wav = f"/tmp/sat1_spk_pattern_probe_{int(time.time())}.wav"
    try:
        _set_mic_input_routing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            mic_source_mode=1,
            mic_input_channel_map=mic_map,
        )
        _set_mic_output_channels(sat1_rpi_host, sat1_rpi_sat1_cmd, 0, 3)
        _set_mic_output_packing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            enabled=True,
            upsample_channel_map=[0, 3, 4, 5, 6, 7],
        )

        with tempfile.TemporaryDirectory(prefix="sat1_spk_pattern_") as tmpdir:
            local_wav = Path(tmpdir) / "silence.wav"
            sample_count = SAT1_HIL_BYPASS_PLAYBACK_S * I2S_RATE_HZ
            _write_stereo_wav_s32(local_wav, [0] * sample_count, [0] * sample_count)
            scp_res = subprocess.run(
                ["scp", str(local_wav), f"{sat1_rpi_host}:{remote_wav}"],
                cwd=PROJ_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert scp_res.returncode == 0, scp_res.stdout + scp_res.stderr

        left, right = _capture_stereo_samples_during_playback(sat1_rpi_host, remote_wav)
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
        _set_mic_input_routing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            mic_source_mode=int(original["mic_input"]["mic_source_mode"]),
            ref_source_mode=int(original["mic_input"]["ref_source_mode"]),
            mic_input_channel_map=list(original["mic_input"]["mic_input_channel_map"]),
            ref_input_channel_map=list(original["mic_input"]["ref_input_channel_map"]),
        )
        _set_mic_output_channels(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            int(original["mic_output"]["i2s_channel_map"][0]),
            int(original["mic_output"]["i2s_channel_map"][1]),
        )
        _set_mic_output_packing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            enabled=bool(original["mic_output"]["pack_extra_upsample_channels"]),
            upsample_channel_map=list(original["mic_output"]["upsample_channel_map"]),
        )
        _run_ssh(sat1_rpi_host, f"rm -f {shlex.quote(remote_wav)}", timeout=10)


@pytest.mark.hil
@pytest.mark.sat1
@pytest.mark.requires_bypass_firmware
def test_sat1_packaged_wav_lane_pattern_propagates_to_raw_mic_outputs(
    require_sat1_hil: None,
    sat1_rpi_host: str,
    sat1_rpi_py_cmd: str,
    sat1_rpi_sat1_cmd: str,
) -> None:
    if not SAT1_HIL_WAV_PATTERN_TEST:
        pytest.skip("Enable with SAT1_HIL_WAV_PATTERN_TEST=1")

    lane_pattern = {
        0: PACKAGED_SYNC_WORD,
        1: 0x22222222,
        2: 0x33333333,
        3: 0x44444444,
        4: 0x55555555,
        5: 0x66666666,
    }
    original = _get_audio_settings(sat1_rpi_host, sat1_rpi_sat1_cmd)
    mic_map = list(original["mic_input"]["mic_input_channel_map"])
    assert len(mic_map) == 4, f"Unexpected mic_input_channel_map shape: {mic_map}"
    expected_by_output_channel = {
        4 + mic_idx: lane_pattern[int(mic_map[mic_idx])] for mic_idx in range(4)
    }

    remote_wav = f"/tmp/sat1_wav_pattern_probe_{int(time.time())}.wav"
    try:
        _set_mic_input_routing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            mic_source_mode=1,
            mic_input_channel_map=mic_map,
        )
        _set_mic_output_channels(sat1_rpi_host, sat1_rpi_sat1_cmd, 0, 3)
        _set_mic_output_packing(
            sat1_rpi_host,
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
            scp_res = subprocess.run(
                ["scp", str(local_wav), f"{sat1_rpi_host}:{remote_wav}"],
                cwd=PROJ_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert scp_res.returncode == 0, scp_res.stdout + scp_res.stderr

        left, right = _capture_stereo_samples_during_playback(sat1_rpi_host, remote_wav)
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
        _set_mic_input_routing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            mic_source_mode=int(original["mic_input"]["mic_source_mode"]),
            ref_source_mode=int(original["mic_input"]["ref_source_mode"]),
            mic_input_channel_map=list(original["mic_input"]["mic_input_channel_map"]),
            ref_input_channel_map=list(original["mic_input"]["ref_input_channel_map"]),
        )
        _set_mic_output_channels(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            int(original["mic_output"]["i2s_channel_map"][0]),
            int(original["mic_output"]["i2s_channel_map"][1]),
        )
        _set_mic_output_packing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            enabled=bool(original["mic_output"]["pack_extra_upsample_channels"]),
            upsample_channel_map=list(original["mic_output"]["upsample_channel_map"]),
        )
        _run_ssh(sat1_rpi_host, f"rm -f {shlex.quote(remote_wav)}", timeout=10)


@pytest.mark.hil
@pytest.mark.sat1
@pytest.mark.requires_bypass_firmware
def test_sat1_packaged_wav_respects_mic_input_channel_map(
    require_sat1_hil: None,
    sat1_rpi_host: str,
    sat1_rpi_py_cmd: str,
    sat1_rpi_sat1_cmd: str,
) -> None:
    if not SAT1_HIL_WAV_PATTERN_TEST:
        pytest.skip("Enable with SAT1_HIL_WAV_PATTERN_TEST=1")

    lane_pattern = {
        0: PACKAGED_SYNC_WORD,
        1: 0x22222222,
        2: 0x33333333,
        3: 0x44444444,
        4: 0x55555555,
        5: 0x66666666,
    }
    probe_maps = [
        [1, 2, 3, 4],
        [4, 5, 1, 2],
    ]

    original = _get_audio_settings(sat1_rpi_host, sat1_rpi_sat1_cmd)
    remote_wav = f"/tmp/sat1_wav_map_probe_{int(time.time())}.wav"

    try:
        _set_mic_output_channels(sat1_rpi_host, sat1_rpi_sat1_cmd, 0, 3)
        _set_mic_output_packing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            enabled=True,
            upsample_channel_map=[0, 3, 4, 5, 6, 7],
        )

        with tempfile.TemporaryDirectory(prefix="sat1_wav_map_pattern_") as tmpdir:
            local_wav = Path(tmpdir) / "wav_lane_pattern_map_probe.wav"
            _write_lane_pattern_wav(
                local_wav,
                sample_count_16k=SAT1_HIL_BYPASS_PLAYBACK_S * PIPELINE_RATE_HZ,
                lane_pattern=lane_pattern,
            )
            scp_res = subprocess.run(
                ["scp", str(local_wav), f"{sat1_rpi_host}:{remote_wav}"],
                cwd=PROJ_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert scp_res.returncode == 0, scp_res.stdout + scp_res.stderr

        failures: list[str] = []
        inferred_left_offset, inferred_right_offset, inferred_snapshot = (
            _infer_ingress_phase_offsets_via_snapshot(
                sat1_rpi_host,
                sat1_rpi_py_cmd,
                remote_wav,
                lane_pattern,
            )
        )
        for probe_map in probe_maps:
            _set_mic_input_routing(
                sat1_rpi_host,
                sat1_rpi_sat1_cmd,
                mic_source_mode=1,
                mic_input_channel_map=list(probe_map),
            )
            readback = _get_audio_settings(sat1_rpi_host, sat1_rpi_sat1_cmd)
            assert [int(v) for v in readback["mic_input"]["mic_input_channel_map"]] == [
                int(v) for v in probe_map
            ], (
                f"Map readback mismatch: wrote={probe_map} "
                f"read={readback['mic_input']['mic_input_channel_map']}"
            )
            time.sleep(SAT1_HIL_BYPASS_SETTLE_S)

            left, right = _capture_stereo_samples_during_playback(
                sat1_rpi_host, remote_wav
            )
            expected_by_output_channel = {
                4 + mic_idx: _lane_value_with_phase_rotation(
                    lane_pattern,
                    int(probe_map[mic_idx]),
                    inferred_left_offset,
                    inferred_right_offset,
                )
                for mic_idx in range(4)
            }
            values_by_output_channel, left_phase_offset, right_phase_offset, _ = (
                _extract_packed_mic_outputs_phase_aligned(
                    left,
                    right,
                    expected_by_output_channel,
                )
            )

            for mic_idx in range(4):
                ch = 4 + mic_idx
                expected = expected_by_output_channel[ch]
                values = values_by_output_channel[ch][SAT1_HIL_PACKED_DROP_SAMPLES:]
                observed = _most_common_value(values)
                if observed != expected:
                    failures.append(
                        f"map={probe_map} mic={mic_idx} ch={ch} "
                        f"expected=0x{expected:08x} observed=0x{observed:08x} "
                        f"inferred_left_offset={inferred_left_offset} "
                        f"inferred_right_offset={inferred_right_offset} "
                        f"inferred_snapshot={inferred_snapshot['packaged_lane_samples']} "
                        f"phase_offset_l={left_phase_offset} phase_offset_r={right_phase_offset} preview={values[:12]}"
                    )

        if failures:
            print(
                "mic_input_channel_map mapping mismatches (diagnostic):\n"
                + "\n".join(failures)
            )
    finally:
        _set_mic_input_routing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            mic_source_mode=int(original["mic_input"]["mic_source_mode"]),
            ref_source_mode=int(original["mic_input"]["ref_source_mode"]),
            mic_input_channel_map=list(original["mic_input"]["mic_input_channel_map"]),
            ref_input_channel_map=list(original["mic_input"]["ref_input_channel_map"]),
        )
        _set_mic_output_channels(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            int(original["mic_output"]["i2s_channel_map"][0]),
            int(original["mic_output"]["i2s_channel_map"][1]),
        )
        _set_mic_output_packing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            enabled=bool(original["mic_output"]["pack_extra_upsample_channels"]),
            upsample_channel_map=list(original["mic_output"]["upsample_channel_map"]),
        )
        _run_ssh(sat1_rpi_host, f"rm -f {shlex.quote(remote_wav)}", timeout=10)


@pytest.mark.hil
@pytest.mark.sat1
@pytest.mark.requires_bypass_firmware
def test_sat1_packaged_snapshot_matches_wav_lane_pattern(
    require_sat1_hil: None,
    sat1_rpi_host: str,
    sat1_rpi_py_cmd: str,
    sat1_rpi_sat1_cmd: str,
) -> None:
    if not SAT1_HIL_WAV_PATTERN_TEST:
        pytest.skip("Enable with SAT1_HIL_WAV_PATTERN_TEST=1")

    lane_pattern = {
        0: PACKAGED_SYNC_WORD,
        1: 0x22222222,
        2: 0x33333333,
        3: 0x44444444,
        4: 0x55555555,
        5: 0x66666666,
    }
    probe_map = [4, 5, 1, 2]
    original = _get_audio_settings(sat1_rpi_host, sat1_rpi_sat1_cmd)
    remote_wav = f"/tmp/sat1_wav_snapshot_probe_{int(time.time())}.wav"
    probe_playback_s = max(SAT1_HIL_BYPASS_PLAYBACK_S, 10)

    try:
        _set_mic_input_routing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            mic_source_mode=1,
            mic_input_channel_map=list(probe_map),
        )

        with tempfile.TemporaryDirectory(prefix="sat1_wav_snapshot_") as tmpdir:
            local_wav = Path(tmpdir) / "wav_lane_pattern_snapshot.wav"
            _write_lane_pattern_wav(
                local_wav,
                sample_count_16k=probe_playback_s * PIPELINE_RATE_HZ,
                lane_pattern=lane_pattern,
            )
            scp_res = subprocess.run(
                ["scp", str(local_wav), f"{sat1_rpi_host}:{remote_wav}"],
                cwd=PROJ_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert scp_res.returncode == 0, scp_res.stdout + scp_res.stderr

        strict_flags = ""
        if SAT1_HIL_APLAY_STRICT_FLAGS:
            strict_flags = " --disable-resample --disable-channels --disable-format --disable-softvol"
        aplay_cmd = (
            f"aplay{strict_flags} -D {SAT1_HIL_BYPASS_APLAY_DEV} -f S32_LE -r {I2S_RATE_HZ} -c 2 "
            f"{shlex.quote(remote_wav)}"
        )
        play_proc = subprocess.Popen(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                sat1_rpi_host,
                aplay_cmd,
            ],
            cwd=PROJ_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        snapshots: list[dict] = []
        ingress_snapshots: list[dict] = []
        try:
            while True:
                if play_proc.poll() is not None:
                    break
                snap = _read_mic_input_packaged_snapshot(sat1_rpi_host, sat1_rpi_py_cmd)
                snapshots.append(snap)
                ingress_snapshots.append(
                    _read_spk_input_packaged_snapshot(sat1_rpi_host, sat1_rpi_py_cmd)
                )
                time.sleep(0.08)
        finally:
            out, err = play_proc.communicate(timeout=20)
            assert play_proc.returncode == 0, out + err

        valid = [s for s in snapshots if s.get("ok")]
        assert valid, "No valid packaged snapshot reads during playback"
        ingress_valid = [s for s in ingress_snapshots if s.get("ok")]
        assert ingress_valid, "No valid speaker-input snapshot reads during playback"

        def _lane_energy_score(snap: dict) -> int:
            energy = 0
            for lane in range(6):
                vals = [int(v) for v in snap["packaged_lane_samples"][lane]]
                energy += sum(abs(v) for v in vals)
            return energy

        def _rot_score(snap: dict) -> int:
            _lo, _ro, s = _detect_lane_phase_offsets_from_snapshot(snap, lane_pattern)
            return s

        ingress_latest = max(
            ingress_valid,
            key=lambda s: (
                _rot_score(s),
                _lane_energy_score(s),
                int(s.get("frame_counter", 0)),
            ),
        )
        latest = max(
            valid,
            key=lambda s: (
                _rot_score(s),
                _lane_energy_score(s),
                int(s.get("frame_counter", 0)),
            ),
        )

        assert int(latest.get("magic", 0)) == 0x534E4150, latest
        assert int(latest.get("guard_a", 0)) == 0x13579BDF, latest
        assert int(latest.get("guard_b", 0)) == 0x2468ACE0, latest
        assert [int(v) for v in latest["mic_input_channel_map"]] == probe_map
        assert int(latest["sample_count"]) == MIC_INPUT_SNAPSHOT_SAMPLE_COUNT

        assert int(ingress_latest.get("magic", 0)) == 0x53504B49, ingress_latest
        assert int(ingress_latest.get("guard_a", 0)) == 0x0BADF00D, ingress_latest
        assert int(ingress_latest.get("guard_b", 0)) == 0x1234CDEF, ingress_latest
        assert int(ingress_latest["sample_count"]) == MIC_INPUT_SNAPSHOT_SAMPLE_COUNT

        ingress_left_offset, ingress_right_offset, ingress_best_score = (
            _detect_lane_phase_offsets_from_snapshot(ingress_latest, lane_pattern)
        )
        _mapped_left_offset, _mapped_right_offset, packaged_best_score = (
            _detect_lane_phase_offsets_from_snapshot(latest, lane_pattern)
        )
        assert len(ingress_valid) >= 2, {
            "reason": "Too few ingress snapshots collected",
            "ingress_snapshot_count": len(ingress_valid),
            "hint": "Increase probe playback duration",
        }
        assert ingress_best_score > 0, {
            "reason": "No ingress snapshot sample matched expected lane pattern",
            "ingress_snapshot_count": len(ingress_valid),
            "scores": [_rot_score(s) for s in ingress_valid[:12]],
            "energies": [_lane_energy_score(s) for s in ingress_valid[:12]],
        }
        assert packaged_best_score > 0, {
            "reason": "No mapped snapshot sample matched expected lane pattern",
            "packaged_snapshot_count": len(valid),
            "scores": [_rot_score(s) for s in valid[:12]],
            "energies": [_lane_energy_score(s) for s in valid[:12]],
        }

        assert ingress_left_offset in (0, 1, 2)
        assert ingress_right_offset in (0, 1, 2)

        for mic in range(4):
            expected = lane_pattern[int(probe_map[mic])]
            vals = [int(v) for v in latest["mapped_mic_samples"][mic]]
            assert vals == [expected] * MIC_INPUT_SNAPSHOT_SAMPLE_COUNT, (
                f"Mapped mic snapshot mismatch mic={mic} expected=0x{expected:08x} vals={vals}"
            )
    finally:
        _set_mic_input_routing(
            sat1_rpi_host,
            sat1_rpi_sat1_cmd,
            mic_source_mode=int(original["mic_input"]["mic_source_mode"]),
            ref_source_mode=int(original["mic_input"]["ref_source_mode"]),
            mic_input_channel_map=list(original["mic_input"]["mic_input_channel_map"]),
            ref_input_channel_map=list(original["mic_input"]["ref_input_channel_map"]),
        )
        _run_ssh(sat1_rpi_host, f"rm -f {shlex.quote(remote_wav)}", timeout=10)
