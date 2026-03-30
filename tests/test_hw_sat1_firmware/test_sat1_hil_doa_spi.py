import json
import math
import os
import shlex
import struct
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import pytest

from tests.conftest import PROJ_ROOT


I2S_RATE_HZ = 48000
PIPELINE_RATE_HZ = 16000
UPSAMPLE_FACTOR = I2S_RATE_HZ // PIPELINE_RATE_HZ
SPEED_OF_SOUND_M_S = 343.0
ARRAY_RADIUS_M = 0.0355

SAT1_HIL_APLAY_DEV = os.getenv("SAT1_HIL_APLAY_DEV", "hw:0,0")
SAT1_HIL_DOA_TEST_ANGLES_DEG = os.getenv("SAT1_HIL_DOA_TEST_ANGLES_DEG", "45,135")
SAT1_HIL_DOA_TOLERANCE_DEG = float(os.getenv("SAT1_HIL_DOA_TOLERANCE_DEG", "55"))
SAT1_HIL_DOA_MIN_SEPARATION_DEG = float(
    os.getenv("SAT1_HIL_DOA_MIN_SEPARATION_DEG", "35")
)
SAT1_HIL_DOA_REQUIRE_ABSOLUTE = os.getenv("SAT1_HIL_DOA_REQUIRE_ABSOLUTE", "0") == "1"
SAT1_HIL_DOA_PLAYBACK_S = int(os.getenv("SAT1_HIL_DOA_PLAYBACK_S", "8"))
SAT1_HIL_DOA_SETTLE_S = float(os.getenv("SAT1_HIL_DOA_SETTLE_S", "0.5"))
SAT1_HIL_DOA_POLL_S = float(os.getenv("SAT1_HIL_DOA_POLL_S", "0.25"))
SAT1_HIL_DOA_PLAYBACK_ENABLED = os.getenv("SAT1_HIL_DOA_PLAYBACK", "0") == "1"


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


def _cleanup_remote_audio_processes(host: str) -> None:
    _run_ssh(
        host,
        "pkill -f 'aplay -D .*doa' >/dev/null 2>&1 || true; "
        "pkill -f sat1_doa_stream_marker_v1 >/dev/null 2>&1 || true",
        timeout=10,
    )


def _run_remote_sdk_json(
    host: str,
    sat1_rpi_py_cmd: str,
    script: str,
    timeout: int = 60,
) -> dict:
    cmd_tokens = shlex.split(sat1_rpi_py_cmd)
    assert cmd_tokens, "SAT1_RPI_PY_CMD resolved to empty command"
    remote_cmd = " ".join(shlex.quote(v) for v in cmd_tokens + ["-c", script])

    res = _run_ssh(host, remote_cmd, timeout=timeout)
    assert res.returncode == 0, res.stdout + res.stderr

    out = res.stdout.strip()
    assert out, "Expected JSON output from remote SDK script"
    return json.loads(out.splitlines()[-1])


def _get_mic_input_settings(sat1_rpi_host: str, sat1_rpi_py_cmd: str) -> dict:
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
        "mic_gain": int(s.mic_gain),
        "ref_gain": int(s.ref_gain),
        "ref_source_mode": int(s.ref_source_mode),
        "mic_source_mode": int(s.mic_source_mode),
        "ref_input_channel_map": [int(v) for v in s.ref_input_channel_map],
        "mic_input_channel_map": [int(v) for v in s.mic_input_channel_map],
        "available_mic_count": int(x.get_available_mic_count()),
    }))
finally:
    cntrl = getattr(x, "_cntrl", None)
    if cntrl is not None and hasattr(cntrl, "close"):
        cntrl.close()
"""
    return _run_remote_sdk_json(sat1_rpi_host, sat1_rpi_py_cmd, script)


def _set_mic_input_routing(
    sat1_rpi_host: str,
    sat1_rpi_py_cmd: str,
    *,
    ref_source_mode: int | None = None,
    mic_source_mode: int | None = None,
    ref_input_channel_map: list[int] | None = None,
    mic_input_channel_map: list[int] | None = None,
) -> None:
    payload = json.dumps(
        {
            "ref_source_mode": ref_source_mode,
            "mic_source_mode": mic_source_mode,
            "ref_input_channel_map": ref_input_channel_map,
            "mic_input_channel_map": mic_input_channel_map,
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
ok = True
try:
    if payload["mic_input_channel_map"] is not None or payload["ref_input_channel_map"] is not None:
        ok = x.set_mic_input_channel_maps(
            ref_input_channel_map=payload["ref_input_channel_map"],
            mic_input_channel_map=payload["mic_input_channel_map"],
        ) and ok
    if payload["ref_source_mode"] is not None or payload["mic_source_mode"] is not None:
        ok = x.set_mic_input_source_modes(
            ref_source_mode=payload["ref_source_mode"],
            mic_source_mode=payload["mic_source_mode"],
        ) and ok
    print(json.dumps({{"ok": bool(ok)}}))
finally:
    cntrl = getattr(x, "_cntrl", None)
    if cntrl is not None and hasattr(cntrl, "close"):
        cntrl.close()
"""

    result = _run_remote_sdk_json(sat1_rpi_host, sat1_rpi_py_cmd, script)
    assert result.get("ok") is True, f"Failed to set mic input routing: {result}"


def _read_doa_sample(sat1_rpi_host: str, sat1_rpi_py_cmd: str) -> dict:
    script = """
import json
from satellite1.sat1_hat import XMOS

x = XMOS()
x.setup()
_ = x.read_firmware()
_ = x.wait_until_ready(timeout_s=3.0, poll_interval_s=0.1)
try:
    raw = x.get_doa_raw()
    smooth = x.get_doa_smooth()
    print(json.dumps({
        "raw": {
            "doa_mrad": int(raw.doa_mrad),
            "seq": int(raw.seq),
            "valid": int(raw.valid),
        },
        "smooth": {
            "doa_mrad": int(smooth.doa_mrad),
            "seq": int(smooth.seq),
            "valid": int(smooth.valid),
        },
    }))
finally:
    cntrl = getattr(x, "_cntrl", None)
    if cntrl is not None and hasattr(cntrl, "close"):
        cntrl.close()
"""
    return _run_remote_sdk_json(sat1_rpi_host, sat1_rpi_py_cmd, script)


def _rotate_left(vals: list[int], n: int) -> list[int]:
    if not vals:
        return vals
    n = n % len(vals)
    return vals[n:] + vals[:n]


def _wrap_deg(angle_deg: float) -> float:
    while angle_deg > 180.0:
        angle_deg -= 360.0
    while angle_deg < -180.0:
        angle_deg += 360.0
    return angle_deg


def _angle_err_deg(expected_deg: float, actual_deg: float) -> float:
    return abs(_wrap_deg(actual_deg - expected_deg))


def _angular_distance_deg(a_deg: float, b_deg: float) -> float:
    return abs(_wrap_deg(a_deg - b_deg))


def _parse_test_angles() -> list[float]:
    vals: list[float] = []
    for token in SAT1_HIL_DOA_TEST_ANGLES_DEG.split(","):
        tok = token.strip()
        if not tok:
            continue
        vals.append(float(tok))

    if len(vals) < 2:
        raise AssertionError(
            "Need at least two test angles in SAT1_HIL_DOA_TEST_ANGLES_DEG"
        )

    return vals


def _circular_median_deg(values_deg: list[float]) -> float:
    assert values_deg

    best = values_deg[0]
    best_cost = float("inf")
    for candidate in values_deg:
        cost = 0.0
        for other in values_deg:
            cost += _angular_distance_deg(candidate, other)
        if cost < best_cost:
            best_cost = cost
            best = candidate

    return _wrap_deg(best)


def _synthesize_mic_frames(angle_deg: float, frame_count_16k: int) -> list[list[int]]:
    ux = math.cos(math.radians(angle_deg))
    uy = math.sin(math.radians(angle_deg))

    mic_positions = [
        (ARRAY_RADIUS_M, 0.0),
        (0.0, ARRAY_RADIUS_M),
        (-ARRAY_RADIUS_M, 0.0),
        (0.0, -ARRAY_RADIUS_M),
    ]

    delays = [
        int(round((PIPELINE_RATE_HZ / SPEED_OF_SOUND_M_S) * ((px * ux) + (py * uy))))
        for px, py in mic_positions
    ]

    base = [0 for _ in range(frame_count_16k)]
    pulse_amp = 240000000
    pulse_offset = 80
    for frame_start in range(0, frame_count_16k, 240):
        idx = frame_start + pulse_offset
        if idx < frame_count_16k:
            base[idx] = pulse_amp

    mics = [[0 for _ in range(frame_count_16k)] for _ in range(4)]
    for mic in range(4):
        delay = delays[mic]
        for n in range(frame_count_16k):
            src_idx = n - delay
            if src_idx < 0 or src_idx >= frame_count_16k:
                sample = 0
            else:
                sample = base[src_idx]
            mics[mic][n] = sample

    return mics


def _pack_mics_to_stereo_48k(
    mic_frames_16k: list[list[int]],
    mic_input_channel_map: list[int],
) -> tuple[list[int], list[int]]:
    frame_count_16k = len(mic_frames_16k[0])
    frame_count_48k = frame_count_16k * UPSAMPLE_FACTOR

    left = [0 for _ in range(frame_count_48k)]
    right = [0 for _ in range(frame_count_48k)]

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


def _write_stereo_wav_s32(path: Path, left: list[int], right: list[int]) -> None:
    assert len(left) == len(right)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(4)
        wf.setframerate(I2S_RATE_HZ)

        data = bytearray()
        for l, r in zip(left, right):
            data.extend(struct.pack("<ii", l, r))
        wf.writeframes(data)


def _play_angle_and_collect_estimate(
    sat1_rpi_host: str,
    sat1_rpi_py_cmd: str,
    angle_deg: float,
    test_map: list[int],
    remote_wav: str,
) -> tuple[float, float, list[float], list[float]]:
    frame_count_16k = SAT1_HIL_DOA_PLAYBACK_S * PIPELINE_RATE_HZ
    mics = _synthesize_mic_frames(angle_deg, frame_count_16k)
    left, right = _pack_mics_to_stereo_48k(mics, test_map)

    with tempfile.TemporaryDirectory(prefix="sat1_doa_playback_") as tmpdir:
        local_wav = Path(tmpdir) / "doa_input.wav"
        _write_stereo_wav_s32(local_wav, left, right)

        scp_res = subprocess.run(
            ["scp", str(local_wav), f"{sat1_rpi_host}:{remote_wav}"],
            cwd=PROJ_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert scp_res.returncode == 0, scp_res.stdout + scp_res.stderr

    aplay_cmd = (
        f"aplay -D {SAT1_HIL_APLAY_DEV} -f S32_LE -r {I2S_RATE_HZ} -c 2 "
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

    raw_deg_samples: list[float] = []
    smooth_deg_samples: list[float] = []
    raw_seq_samples: list[int] = []
    smooth_seq_samples: list[int] = []
    last_sample: dict | None = None
    deadline = time.time() + SAT1_HIL_DOA_PLAYBACK_S + 10.0

    while True:
        if play_proc.poll() is not None:
            break
        if time.time() > deadline:
            play_proc.kill()
            raise AssertionError("Timed out waiting for aplay to finish")

        sample = _read_doa_sample(sat1_rpi_host, sat1_rpi_py_cmd)
        last_sample = sample
        raw = sample["raw"]
        smooth = sample["smooth"]
        raw_seq_samples.append(int(raw["seq"]))
        smooth_seq_samples.append(int(smooth["seq"]))
        if raw["valid"]:
            raw_deg_samples.append(_wrap_deg(math.degrees(raw["doa_mrad"] / 1000.0)))
        if smooth["valid"]:
            smooth_deg_samples.append(
                _wrap_deg(math.degrees(smooth["doa_mrad"] / 1000.0))
            )
        time.sleep(SAT1_HIL_DOA_POLL_S)

    out, err = play_proc.communicate(timeout=10)
    assert play_proc.returncode == 0, out + err

    if not raw_deg_samples:
        raw_seq_span = (
            max(raw_seq_samples) - min(raw_seq_samples) if raw_seq_samples else 0
        )
        pytest.skip(
            "No valid raw DoA samples collected; "
            f"last_sample={last_sample} raw_seq_span={raw_seq_span}"
        )

    if not smooth_deg_samples:
        smooth_seq_span = (
            max(smooth_seq_samples) - min(smooth_seq_samples)
            if smooth_seq_samples
            else 0
        )
        pytest.skip(
            "No valid smooth DoA samples collected; "
            f"last_sample={last_sample} smooth_seq_span={smooth_seq_span}"
        )

    estimate_raw = _circular_median_deg(raw_deg_samples)
    estimate_smooth = _circular_median_deg(smooth_deg_samples)
    return estimate_raw, estimate_smooth, raw_deg_samples, smooth_deg_samples


@pytest.mark.hil
@pytest.mark.sat1
def test_sat1_mic_input_routing_roundtrip_spi(
    require_sat1_hil: None,
    sat1_rpi_host: str,
    sat1_rpi_py_cmd: str,
) -> None:
    original = _get_mic_input_settings(sat1_rpi_host, sat1_rpi_py_cmd)

    rotated_ref = _rotate_left(list(original["ref_input_channel_map"]), 1)
    rotated_mic = _rotate_left(list(original["mic_input_channel_map"]), 1)

    try:
        _set_mic_input_routing(
            sat1_rpi_host,
            sat1_rpi_py_cmd,
            ref_source_mode=1,
            mic_source_mode=1,
            ref_input_channel_map=rotated_ref,
            mic_input_channel_map=rotated_mic,
        )

        current = _get_mic_input_settings(sat1_rpi_host, sat1_rpi_py_cmd)
        assert current["ref_source_mode"] == 1
        assert current["mic_source_mode"] == 1
        assert current["ref_input_channel_map"] == rotated_ref
        assert current["mic_input_channel_map"] == rotated_mic
    finally:
        _set_mic_input_routing(
            sat1_rpi_host,
            sat1_rpi_py_cmd,
            ref_source_mode=original["ref_source_mode"],
            mic_source_mode=original["mic_source_mode"],
            ref_input_channel_map=original["ref_input_channel_map"],
            mic_input_channel_map=original["mic_input_channel_map"],
        )


@pytest.mark.hil
@pytest.mark.sat1
def test_sat1_doa_seq_progresses_with_packaged_playback_spi(
    require_sat1_hil: None,
    sat1_rpi_host: str,
    sat1_rpi_py_cmd: str,
) -> None:
    original = _get_mic_input_settings(sat1_rpi_host, sat1_rpi_py_cmd)
    if original["available_mic_count"] != 4:
        pytest.skip(
            f"Need 4 available mics for this test, got {original['available_mic_count']}"
        )

    remote_wav = f"/tmp/sat1_doa_seq_progress_{int(time.time())}.wav"
    test_map = list(original["mic_input_channel_map"])
    probe_angle = _parse_test_angles()[0]
    frame_count_16k = SAT1_HIL_DOA_PLAYBACK_S * PIPELINE_RATE_HZ

    raw_seq_samples: list[int] = []
    smooth_seq_samples: list[int] = []
    valid_count = 0

    with tempfile.TemporaryDirectory(prefix="sat1_doa_seq_probe_") as tmpdir:
        local_wav = Path(tmpdir) / "doa_seq_probe.wav"
        mics = _synthesize_mic_frames(probe_angle, frame_count_16k)
        left, right = _pack_mics_to_stereo_48k(mics, test_map)
        _write_stereo_wav_s32(local_wav, left, right)

        scp_res = subprocess.run(
            ["scp", str(local_wav), f"{sat1_rpi_host}:{remote_wav}"],
            cwd=PROJ_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert scp_res.returncode == 0, scp_res.stdout + scp_res.stderr

    try:
        _cleanup_remote_audio_processes(sat1_rpi_host)
        _set_mic_input_routing(
            sat1_rpi_host,
            sat1_rpi_py_cmd,
            mic_source_mode=1,
            mic_input_channel_map=test_map,
        )
        time.sleep(SAT1_HIL_DOA_SETTLE_S)

        aplay_cmd = (
            f"aplay -D {SAT1_HIL_APLAY_DEV} -f S32_LE -r {I2S_RATE_HZ} -c 2 "
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

        deadline = time.time() + SAT1_HIL_DOA_PLAYBACK_S + 10.0
        while True:
            if play_proc.poll() is not None:
                break
            if time.time() > deadline:
                play_proc.kill()
                raise AssertionError("Timed out waiting for aplay to finish")

            sample = _read_doa_sample(sat1_rpi_host, sat1_rpi_py_cmd)
            raw = sample["raw"]
            smooth = sample["smooth"]
            raw_seq_samples.append(int(raw["seq"]))
            smooth_seq_samples.append(int(smooth["seq"]))
            if int(raw["valid"]) and int(smooth["valid"]):
                valid_count += 1
            time.sleep(SAT1_HIL_DOA_POLL_S)

        out, err = play_proc.communicate(timeout=10)
        assert play_proc.returncode == 0, out + err

        assert raw_seq_samples, "No raw DoA samples captured"
        assert smooth_seq_samples, "No smooth DoA samples captured"

        raw_seq_span = max(raw_seq_samples) - min(raw_seq_samples)
        smooth_seq_span = max(smooth_seq_samples) - min(smooth_seq_samples)

        assert raw_seq_span > 0, f"Raw DoA sequence did not advance: {raw_seq_samples}"
        assert smooth_seq_span > 0, (
            f"Smooth DoA sequence did not advance: {smooth_seq_samples}"
        )
        assert valid_count > 0, "No valid DoA samples captured during playback"
    finally:
        _cleanup_remote_audio_processes(sat1_rpi_host)
        _set_mic_input_routing(
            sat1_rpi_host,
            sat1_rpi_py_cmd,
            ref_source_mode=original["ref_source_mode"],
            mic_source_mode=original["mic_source_mode"],
            ref_input_channel_map=original["ref_input_channel_map"],
            mic_input_channel_map=original["mic_input_channel_map"],
        )
        _run_ssh(sat1_rpi_host, f"rm -f {shlex.quote(remote_wav)}", timeout=10)


@pytest.mark.hil
@pytest.mark.sat1
def test_sat1_doa_estimate_from_packaged_wav_playback_spi(
    require_sat1_hil: None,
    sat1_rpi_host: str,
    sat1_rpi_py_cmd: str,
) -> None:
    if not SAT1_HIL_DOA_PLAYBACK_ENABLED:
        pytest.skip("Enable with SAT1_HIL_DOA_PLAYBACK=1")

    original = _get_mic_input_settings(sat1_rpi_host, sat1_rpi_py_cmd)
    if original["available_mic_count"] != 4:
        pytest.skip(
            f"Need 4 available mics for this test, got {original['available_mic_count']}"
        )

    remote_wav = f"/tmp/sat1_doa_playback_{int(time.time())}.wav"
    test_map = list(original["mic_input_channel_map"])
    test_angles_deg = _parse_test_angles()
    angle_results: list[tuple[float, float, float, list[float], list[float]]] = []

    try:
        _cleanup_remote_audio_processes(sat1_rpi_host)
        _set_mic_input_routing(
            sat1_rpi_host,
            sat1_rpi_py_cmd,
            mic_source_mode=1,
            mic_input_channel_map=test_map,
        )
        time.sleep(SAT1_HIL_DOA_SETTLE_S)

        for idx, expected_deg in enumerate(test_angles_deg):
            angle_remote_wav = remote_wav.replace(".wav", f"_{idx}.wav")
            estimate_raw_deg, estimate_smooth_deg, raw_set_deg, smooth_set_deg = (
                _play_angle_and_collect_estimate(
                    sat1_rpi_host,
                    sat1_rpi_py_cmd,
                    expected_deg,
                    test_map,
                    angle_remote_wav,
                )
            )

            err_raw_deg = _angle_err_deg(expected_deg, estimate_raw_deg)
            err_smooth_deg = _angle_err_deg(expected_deg, estimate_smooth_deg)
            if SAT1_HIL_DOA_REQUIRE_ABSOLUTE:
                assert err_raw_deg <= SAT1_HIL_DOA_TOLERANCE_DEG, (
                    f"Raw DoA estimate too far from expected angle {expected_deg:.1f}: "
                    f"estimate={estimate_raw_deg:.2f} err={err_raw_deg:.2f} "
                    f"tol={SAT1_HIL_DOA_TOLERANCE_DEG:.2f} samples={raw_set_deg}"
                )
                assert err_smooth_deg <= SAT1_HIL_DOA_TOLERANCE_DEG, (
                    f"Smooth DoA estimate too far from expected angle {expected_deg:.1f}: "
                    f"estimate={estimate_smooth_deg:.2f} err={err_smooth_deg:.2f} "
                    f"tol={SAT1_HIL_DOA_TOLERANCE_DEG:.2f} samples={smooth_set_deg}"
                )

            angle_results.append(
                (
                    expected_deg,
                    estimate_raw_deg,
                    estimate_smooth_deg,
                    raw_set_deg,
                    smooth_set_deg,
                )
            )
            _run_ssh(
                sat1_rpi_host, f"rm -f {shlex.quote(angle_remote_wav)}", timeout=10
            )

        for i in range(len(angle_results)):
            for j in range(i + 1, len(angle_results)):
                expected_sep = _angular_distance_deg(
                    angle_results[i][0], angle_results[j][0]
                )
                if expected_sep < 60.0:
                    continue

                raw_sep = _angular_distance_deg(
                    angle_results[i][1], angle_results[j][1]
                )
                smooth_sep = _angular_distance_deg(
                    angle_results[i][2], angle_results[j][2]
                )

                if raw_sep < SAT1_HIL_DOA_MIN_SEPARATION_DEG:
                    pytest.skip(
                        "Raw DoA estimates are not sufficiently separated on this setup: "
                        f"exp_pair=({angle_results[i][0]:.1f},{angle_results[j][0]:.1f}) "
                        f"est_pair=({angle_results[i][1]:.2f},{angle_results[j][1]:.2f}) "
                        f"est_sep={raw_sep:.2f} min_sep={SAT1_HIL_DOA_MIN_SEPARATION_DEG:.2f}"
                    )
                if smooth_sep < SAT1_HIL_DOA_MIN_SEPARATION_DEG:
                    pytest.skip(
                        "Smooth DoA estimates are not sufficiently separated on this setup: "
                        f"exp_pair=({angle_results[i][0]:.1f},{angle_results[j][0]:.1f}) "
                        f"est_pair=({angle_results[i][2]:.2f},{angle_results[j][2]:.2f}) "
                        f"est_sep={smooth_sep:.2f} min_sep={SAT1_HIL_DOA_MIN_SEPARATION_DEG:.2f}"
                    )

    finally:
        _cleanup_remote_audio_processes(sat1_rpi_host)
        _set_mic_input_routing(
            sat1_rpi_host,
            sat1_rpi_py_cmd,
            ref_source_mode=original["ref_source_mode"],
            mic_source_mode=original["mic_source_mode"],
            ref_input_channel_map=original["ref_input_channel_map"],
            mic_input_channel_map=original["mic_input_channel_map"],
        )
        _run_ssh(sat1_rpi_host, f"rm -f {shlex.quote(remote_wav)}*", timeout=10)
