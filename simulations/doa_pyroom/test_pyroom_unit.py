import math

import pytest


DOA4_FRAME_ADVANCE = 240
DOA4_FFT_LENGTH = 256
DOA4_TAIL_SAMPLES = DOA4_FFT_LENGTH - DOA4_FRAME_ADVANCE
DOA4_MAX_LAG_SAMPLES = 4
DOA4_ARRAY_RADIUS_M = 0.0355
DOA4_SAMPLE_RATE_HZ = 16000.0
DOA4_SPEED_OF_SOUND = 343.0


def _wrap_deg(deg: float) -> float:
    while deg > 180.0:
        deg -= 360.0
    while deg < -180.0:
        deg += 360.0
    return deg


def _angle_error_deg(expected_deg: float, actual_deg: float) -> float:
    return abs(_wrap_deg(actual_deg - expected_deg))


def _angle_error_opposite_deg(expected_deg: float, actual_deg: float) -> float:
    return abs(_wrap_deg((actual_deg + 180.0) - expected_deg))


def _doa4_estimate_from_lags(lag10: int, lag20: int, lag30: int) -> float:
    r = DOA4_ARRAY_RADIUS_M
    fs = DOA4_SAMPLE_RATE_HZ
    c = DOA4_SPEED_OF_SOUND

    a1x, a1y = r, -r
    a2x, a2y = 0.0, -2.0 * r
    a3x, a3y = -r, -r

    b1 = c * (lag10 / fs)
    b2 = c * (lag20 / fs)
    b3 = c * (lag30 / fs)

    ata00 = a1x * a1x + a2x * a2x + a3x * a3x
    ata01 = a1x * a1y + a2x * a2y + a3x * a3y
    ata11 = a1y * a1y + a2y * a2y + a3y * a3y

    atb0 = a1x * b1 + a2x * b2 + a3x * b3
    atb1 = a1y * b1 + a2y * b2 + a3y * b3

    det = ata00 * ata11 - ata01 * ata01
    if abs(det) < 1e-12:
        return 0.0

    inv00 = ata11 / det
    inv01 = -ata01 / det
    inv11 = ata00 / det

    ux = inv00 * atb0 + inv01 * atb1
    uy = inv01 * atb0 + inv11 * atb1
    norm = math.sqrt((ux * ux) + (uy * uy))
    if norm > 1e-12:
        ux /= norm
        uy /= norm

    return math.atan2(uy, ux)


def _signed_lag(idx: int, n: int) -> int:
    return idx - n if idx > (n // 2) else idx


def _gcc_phat_lag(sig_a, sig_b, max_lag: int) -> int:
    np = pytest.importorskip("numpy")

    a = np.asarray(sig_a, dtype=np.float64)
    b = np.asarray(sig_b, dtype=np.float64)

    A = np.fft.rfft(a, n=DOA4_FFT_LENGTH)
    B = np.fft.rfft(b, n=DOA4_FFT_LENGTH)

    z = A * np.conj(B)
    mag = np.abs(z)
    mag[mag < 1e-12] = 1e-12
    z /= mag

    corr = np.fft.irfft(z, n=DOA4_FFT_LENGTH)

    best_idx = 0
    best_val = corr[0]
    for idx in range(0, max_lag + 1):
        if corr[idx] > best_val:
            best_val = corr[idx]
            best_idx = idx
    for idx in range(DOA4_FFT_LENGTH - max_lag, DOA4_FFT_LENGTH):
        if corr[idx] > best_val:
            best_val = corr[idx]
            best_idx = idx

    return _signed_lag(int(best_idx), DOA4_FFT_LENGTH)


def _simulate_pyroom_mics(angle_deg: float, duration_s: float = 1.2):
    np = pytest.importorskip("numpy")
    pra = pytest.importorskip("pyroomacoustics")

    room = pra.ShoeBox(
        [6.0, 6.0, 2.6], fs=int(DOA4_SAMPLE_RATE_HZ), max_order=0, absorption=0.05
    )

    center = np.array([3.0, 3.0, 1.2])
    mic_xyz = np.array(
        [
            [0.0, DOA4_ARRAY_RADIUS_M, 0.0, -DOA4_ARRAY_RADIUS_M],
            [DOA4_ARRAY_RADIUS_M, 0.0, -DOA4_ARRAY_RADIUS_M, 0.0],
            [0.0, 0.0, 0.0, 0.0],
        ]
    )
    room.add_microphone_array(
        pra.MicrophoneArray(center[:, None] + mic_xyz, int(DOA4_SAMPLE_RATE_HZ))
    )

    dist = 2.0
    az = math.radians(angle_deg)
    src = center + np.array([dist * math.cos(az), dist * math.sin(az), 0.0])
    src[0] = min(max(src[0], 0.5), 5.5)
    src[1] = min(max(src[1], 0.5), 5.5)

    n = int(duration_s * DOA4_SAMPLE_RATE_HZ)
    t = np.arange(n, dtype=np.float32) / DOA4_SAMPLE_RATE_HZ
    chirp = np.sin(
        2.0 * np.pi * (300.0 * t + 0.5 * ((3200.0 - 300.0) / duration_s) * t * t)
    )
    rng = np.random.default_rng(1234)
    chirp += 0.03 * rng.standard_normal(n).astype(np.float32)

    room.add_source(src, signal=chirp.astype(np.float32))
    room.simulate()
    return room.mic_array.signals[:, :n]


def _estimate_angle_series_deg(mics) -> list[float]:
    np = pytest.importorskip("numpy")

    tails = np.zeros((4, DOA4_TAIL_SAMPLES), dtype=np.float64)
    out_deg: list[float] = []

    n = mics.shape[1]
    for start in range(0, n - DOA4_FRAME_ADVANCE + 1, DOA4_FRAME_ADVANCE):
        frame = np.zeros((4, DOA4_FFT_LENGTH), dtype=np.float64)
        frame[:, :DOA4_TAIL_SAMPLES] = tails
        frame[:, DOA4_TAIL_SAMPLES:] = mics[:, start : start + DOA4_FRAME_ADVANCE]
        tails = frame[:, -DOA4_TAIL_SAMPLES:]

        lag10 = _gcc_phat_lag(frame[1], frame[0], DOA4_MAX_LAG_SAMPLES)
        lag20 = _gcc_phat_lag(frame[2], frame[0], DOA4_MAX_LAG_SAMPLES)
        lag30 = _gcc_phat_lag(frame[3], frame[0], DOA4_MAX_LAG_SAMPLES)
        doa_rad = _doa4_estimate_from_lags(lag10, lag20, lag30)
        out_deg.append(_wrap_deg(math.degrees(doa_rad)))

    return out_deg


@pytest.mark.parametrize("angle_deg", [0.0, 45.0, 90.0, 135.0, -90.0])
def test_pyroom_geometry_matches_doa_estimator_order(angle_deg: float) -> None:
    mics = _simulate_pyroom_mics(angle_deg)
    estimates = _estimate_angle_series_deg(mics)
    assert estimates

    settled = estimates[2:] if len(estimates) > 3 else estimates
    median_deg = sorted(settled)[len(settled) // 2]
    err_direct = _angle_error_deg(angle_deg, median_deg)
    err_opposite = _angle_error_opposite_deg(angle_deg, median_deg)
    best_err = min(err_direct, err_opposite)

    assert best_err < 35.0, (
        "Expected pyroom synthetic angle to match estimator with either direct "
        "or opposite convention. "
        f"angle={angle_deg:.1f} estimate={median_deg:.1f} "
        f"err_direct={err_direct:.1f} err_opposite={err_opposite:.1f}"
    )


def test_pyroom_doa_convention_is_consistent() -> None:
    angles = [0.0, 45.0, 90.0, 135.0, -90.0]
    direct_wins = 0
    opposite_wins = 0

    for angle_deg in angles:
        mics = _simulate_pyroom_mics(angle_deg)
        estimates = _estimate_angle_series_deg(mics)
        settled = estimates[2:] if len(estimates) > 3 else estimates
        median_deg = sorted(settled)[len(settled) // 2]
        err_direct = _angle_error_deg(angle_deg, median_deg)
        err_opposite = _angle_error_opposite_deg(angle_deg, median_deg)

        if err_direct <= err_opposite:
            direct_wins += 1
        else:
            opposite_wins += 1

    assert max(direct_wins, opposite_wins) >= 4, (
        "Expected one angle convention to dominate; "
        f"direct_wins={direct_wins}, opposite_wins={opposite_wins}"
    )


def test_pyroom_channel_order_mismatch_is_detectable() -> None:
    angle_deg = 45.0
    mics = _simulate_pyroom_mics(angle_deg)

    swapped = mics.copy()
    swapped[[1, 3], :] = swapped[[3, 1], :]

    estimates = _estimate_angle_series_deg(swapped)
    settled = estimates[2:] if len(estimates) > 3 else estimates
    median_deg = sorted(settled)[len(settled) // 2]
    err = _angle_error_deg(angle_deg, median_deg)

    assert err > 20.0, (
        f"Expected channel-order mismatch to produce noticeable error, got err={err:.1f}"
    )
