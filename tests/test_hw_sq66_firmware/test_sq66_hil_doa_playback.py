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

SQ66_HIL_APLAY_DEV = os.getenv("SQ66_HIL_APLAY_DEV", "hw:0,0")
SQ66_HIL_DOA_TEST_ANGLES_DEG = os.getenv("SQ66_HIL_DOA_TEST_ANGLES_DEG", "45,135")
SQ66_HIL_DOA_TOLERANCE_DEG = float(os.getenv("SQ66_HIL_DOA_TOLERANCE_DEG", "50"))
SQ66_HIL_DOA_MIN_SEPARATION_DEG = float(
    os.getenv("SQ66_HIL_DOA_MIN_SEPARATION_DEG", "35")
)
SQ66_HIL_DOA_REQUIRE_ABSOLUTE = os.getenv("SQ66_HIL_DOA_REQUIRE_ABSOLUTE", "0") == "1"
SQ66_HIL_DOA_PLAYBACK_S = int(os.getenv("SQ66_HIL_DOA_PLAYBACK_S", "8"))
SQ66_HIL_DOA_SETTLE_S = float(os.getenv("SQ66_HIL_DOA_SETTLE_S", "0.5"))
SQ66_HIL_DOA_PLAYBACK_ENABLED = os.getenv("SQ66_HIL_DOA_PLAYBACK", "0") == "1"


def _run_ssh(
    host: str,
    cmd: str,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, cmd],
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


def _run_remote_sdk_json(
    host: str,
    sq66_rpi_sat1_cmd: str,
    script: str,
    timeout: int = 60,
) -> dict:
    env_tokens, python_cmd = _parse_remote_python_command(sq66_rpi_sat1_cmd)
    remote_cmd = " ".join(env_tokens + [python_cmd, "-c", shlex.quote(script)])

    res = _run_ssh(host, remote_cmd, timeout=timeout)
    assert res.returncode == 0, res.stdout + res.stderr

    out = res.stdout.strip()
    assert out, "Expected JSON output from remote SDK script"
    return json.loads(out.splitlines()[-1])


def _get_mic_input_settings(sq66_rpi_host: str, sq66_rpi_sat1_cmd: str) -> dict:
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
    return _run_remote_sdk_json(sq66_rpi_host, sq66_rpi_sat1_cmd, script)


def _set_mic_input_routing(
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
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

    result = _run_remote_sdk_json(sq66_rpi_host, sq66_rpi_sat1_cmd, script)
    assert result.get("ok") is True, f"Failed to set mic input routing: {result}"


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
    for token in SQ66_HIL_DOA_TEST_ANGLES_DEG.split(","):
        tok = token.strip()
        if not tok:
            continue
        vals.append(float(tok))

    if len(vals) < 2:
        raise AssertionError(
            "Need at least two test angles in SQ66_HIL_DOA_TEST_ANGLES_DEG"
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

    # Integer sample delays at 16 kHz
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


def _read_new_doa_samples(log_path: Path, start_pos: int) -> tuple[list[float], int]:
    text = ""
    with log_path.open("rb") as f:
        f.seek(start_pos)
        raw = f.read()
        end_pos = f.tell()
        text = raw.decode("utf-8", errors="ignore")

    samples_rad: list[float] = []
    marker = "DoA angle mrad="
    for line in text.splitlines():
        idx = line.find(marker)
        if idx < 0:
            continue
        value_txt = line[idx + len(marker) :].strip()
        try:
            mrad = int(value_txt)
        except ValueError:
            continue
        samples_rad.append(mrad / 1000.0)

    return samples_rad, end_pos


def _collect_doa_samples_with_timeout(
    log_path: Path,
    start_pos: int,
    timeout_s: float,
    min_samples: int,
) -> list[float]:
    deadline = time.time() + timeout_s
    cursor = start_pos
    collected: list[float] = []

    while time.time() < deadline:
        samples, cursor = _read_new_doa_samples(log_path, cursor)
        if samples:
            collected.extend(samples)
            if len(collected) >= min_samples:
                break
        time.sleep(0.25)

    return collected


def _play_angle_and_collect_estimate(
    sq66_rpi_host: str,
    xscope_log_path: Path,
    angle_deg: float,
    test_map: list[int],
    remote_wav: str,
) -> tuple[float, list[float]]:
    frame_count_16k = SQ66_HIL_DOA_PLAYBACK_S * PIPELINE_RATE_HZ
    mics = _synthesize_mic_frames(angle_deg, frame_count_16k)
    left, right = _pack_mics_to_stereo_48k(mics, test_map)

    with tempfile.TemporaryDirectory(prefix="sq66_doa_playback_") as tmpdir:
        local_wav = Path(tmpdir) / "doa_input.wav"
        _write_stereo_wav_s32(local_wav, left, right)

        scp_res = subprocess.run(
            ["scp", str(local_wav), f"{sq66_rpi_host}:{remote_wav}"],
            cwd=PROJ_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert scp_res.returncode == 0, scp_res.stdout + scp_res.stderr

    start_pos = xscope_log_path.stat().st_size
    aplay_cmd = (
        f"aplay -D {SQ66_HIL_APLAY_DEV} -f S32_LE -r {I2S_RATE_HZ} -c 2 "
        f"{shlex.quote(remote_wav)}"
    )
    play_res = _run_ssh(
        sq66_rpi_host,
        aplay_cmd,
        timeout=SQ66_HIL_DOA_PLAYBACK_S + 20,
    )
    assert play_res.returncode == 0, play_res.stdout + play_res.stderr

    doa_samples_rad = _collect_doa_samples_with_timeout(
        xscope_log_path,
        start_pos,
        timeout_s=10.0,
        min_samples=3,
    )
    assert doa_samples_rad, f"No DoA samples found in xscope log for angle {angle_deg}"

    doa_samples_deg = [_wrap_deg(math.degrees(v)) for v in doa_samples_rad]
    estimate_deg = _circular_median_deg(doa_samples_deg)
    return estimate_deg, doa_samples_deg


@pytest.mark.hil
@pytest.mark.sq66
def test_sq66_doa_estimate_from_packaged_wav_playback(
    require_sq66_hil: None,
    ensure_sq66_running: None,
    sq66_rpi_host: str,
    sq66_rpi_sat1_cmd: str,
) -> None:
    if not SQ66_HIL_DOA_PLAYBACK_ENABLED:
        pytest.skip("Enable with SQ66_HIL_DOA_PLAYBACK=1")

    xscope_log = os.getenv("SQ66_HIL_XSCOPE_LOG", "").strip()
    if not xscope_log:
        pytest.skip("Set SQ66_HIL_XSCOPE_LOG to the running xscope log path")

    xscope_log_path = Path(xscope_log)
    if not xscope_log_path.exists():
        pytest.skip(f"xscope log file does not exist: {xscope_log_path}")

    original = _get_mic_input_settings(sq66_rpi_host, sq66_rpi_sat1_cmd)
    if original["available_mic_count"] != 4:
        pytest.skip(
            f"Need 4 available mics for this test, got {original['available_mic_count']}"
        )

    remote_wav = f"/tmp/sq66_doa_playback_{int(time.time())}.wav"
    test_map = list(original["mic_input_channel_map"])
    test_angles_deg = _parse_test_angles()
    angle_results: list[tuple[float, float, list[float]]] = []

    try:
        _set_mic_input_routing(
            sq66_rpi_host,
            sq66_rpi_sat1_cmd,
            mic_source_mode=1,
            mic_input_channel_map=test_map,
        )
        time.sleep(SQ66_HIL_DOA_SETTLE_S)

        for idx, expected_deg in enumerate(test_angles_deg):
            angle_remote_wav = remote_wav.replace(".wav", f"_{idx}.wav")
            estimate_deg, sample_set_deg = _play_angle_and_collect_estimate(
                sq66_rpi_host,
                xscope_log_path,
                expected_deg,
                test_map,
                angle_remote_wav,
            )

            err_deg = _angle_err_deg(expected_deg, estimate_deg)
            if SQ66_HIL_DOA_REQUIRE_ABSOLUTE:
                assert err_deg <= SQ66_HIL_DOA_TOLERANCE_DEG, (
                    f"DoA estimate too far from expected for angle {expected_deg:.1f} deg: "
                    f"estimate={estimate_deg:.2f} deg err={err_deg:.2f} deg "
                    f"tol={SQ66_HIL_DOA_TOLERANCE_DEG:.2f} deg samples={sample_set_deg}"
                )

            angle_results.append((expected_deg, estimate_deg, sample_set_deg))
            _run_ssh(
                sq66_rpi_host, f"rm -f {shlex.quote(angle_remote_wav)}", timeout=10
            )

        # Strong anti-regression check: measured angles must be meaningfully distinct.
        for i in range(len(angle_results)):
            for j in range(i + 1, len(angle_results)):
                expected_sep = _angular_distance_deg(
                    angle_results[i][0], angle_results[j][0]
                )
                if expected_sep < 60.0:
                    continue
                est_sep = _angular_distance_deg(
                    angle_results[i][1], angle_results[j][1]
                )
                assert est_sep >= SQ66_HIL_DOA_MIN_SEPARATION_DEG, (
                    "Estimated DoA angles are not sufficiently separated: "
                    f"exp_pair=({angle_results[i][0]:.1f},{angle_results[j][0]:.1f}) "
                    f"est_pair=({angle_results[i][1]:.2f},{angle_results[j][1]:.2f}) "
                    f"est_sep={est_sep:.2f} deg min_sep={SQ66_HIL_DOA_MIN_SEPARATION_DEG:.2f} deg"
                )

    finally:
        _set_mic_input_routing(
            sq66_rpi_host,
            sq66_rpi_sat1_cmd,
            ref_source_mode=original["ref_source_mode"],
            mic_source_mode=original["mic_source_mode"],
            ref_input_channel_map=original["ref_input_channel_map"],
            mic_input_channel_map=original["mic_input_channel_map"],
        )
        _run_ssh(sq66_rpi_host, f"rm -f {shlex.quote(remote_wav)}*", timeout=10)
