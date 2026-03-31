from pathlib import Path

from tests.conftest import PROJ_ROOT


DOA_FIXTURE_DIR = PROJ_ROOT / "tests" / "test_doa" / "fixtures" / "lag_synth"

DOA_FIXTURE_WAV_BY_ANGLE = {
    -135: DOA_FIXTURE_DIR / "doa_lagsynth_m135.wav",
    -90: DOA_FIXTURE_DIR / "doa_lagsynth_m090.wav",
    -45: DOA_FIXTURE_DIR / "doa_lagsynth_m045.wav",
    0: DOA_FIXTURE_DIR / "doa_lagsynth_p000.wav",
    45: DOA_FIXTURE_DIR / "doa_lagsynth_p045.wav",
    90: DOA_FIXTURE_DIR / "doa_lagsynth_p090.wav",
    135: DOA_FIXTURE_DIR / "doa_lagsynth_p135.wav",
    180: DOA_FIXTURE_DIR / "doa_lagsynth_p180.wav",
}


def _wrap_deg(angle_deg: float) -> float:
    while angle_deg > 180.0:
        angle_deg -= 360.0
    while angle_deg < -180.0:
        angle_deg += 360.0
    return angle_deg


def normalize_fixture_angle_key(angle_deg: float) -> int:
    key = int(round(_wrap_deg(angle_deg)))
    if key == -180:
        key = 180
    return key


def fixture_wav_for_angle(angle_deg: float) -> Path | None:
    key = normalize_fixture_angle_key(angle_deg)
    path = DOA_FIXTURE_WAV_BY_ANGLE.get(key)
    if path is None or not path.is_file():
        return None
    return path


def supported_fixture_angles() -> list[int]:
    return sorted(DOA_FIXTURE_WAV_BY_ANGLE.keys())


def fixture_missing_angles(angles_deg: list[float]) -> list[float]:
    missing: list[float] = []
    for angle in angles_deg:
        if fixture_wav_for_angle(angle) is None:
            missing.append(angle)
    return missing


def fixture_wav_required(angle_deg: float) -> Path:
    path = fixture_wav_for_angle(angle_deg)
    if path is None:
        key = normalize_fixture_angle_key(angle_deg)
        raise FileNotFoundError(
            f"No DoA fixture WAV for angle {angle_deg} (normalized key: {key})"
        )
    return path
