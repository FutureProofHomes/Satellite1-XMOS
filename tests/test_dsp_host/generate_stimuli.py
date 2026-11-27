#!/usr/bin/env python3
"""Generate 12 test stimuli for the DSP pipeline test harness.

Output: 4-channel, 32-bit, 16 kHz WAV files in ./stimuli/
Channel layout: [mic1, mic2, ref1, ref2]
"""
import numpy as np
from pathlib import Path
from scipy.io import wavfile

SR = 16000
OUT_DIR = Path(__file__).parent / "stimuli"


def write_wav(name: str, data: np.ndarray):
    """Write int32 WAV. data shape: (n_samples, 4)."""
    assert data.dtype == np.int32
    assert data.shape[1] == 4
    path = OUT_DIR / name
    wavfile.write(str(path), SR, data)
    print(f"  {path.name}: {data.shape[0]/SR:.1f}s, {data.nbytes/1e6:.1f} MB")


def silence(duration_s: float) -> np.ndarray:
    n = int(duration_s * SR)
    return np.zeros((n, 4), dtype=np.int32)


def make_speech(duration_s: float, level_dbfs: float = -6.0) -> np.ndarray:
    """Synthetic speech-like signal: amplitude-modulated multi-tone."""
    n = int(duration_s * SR)
    t = np.arange(n) / SR
    # Base formants
    sig = (
        0.5 * np.sin(2 * np.pi * 170 * t) +
        0.3 * np.sin(2 * np.pi * 220 * t) +
        0.2 * np.sin(2 * np.pi * 310 * t) +
        0.1 * np.sin(2 * np.pi * 440 * t)
    )
    # Syllable AM at ~3 Hz with random phase per syllable
    syllable_rate = 3.0
    n_syl = int(duration_s * syllable_rate)
    am = np.zeros(n)
    for i in range(n_syl):
        start = int(i / syllable_rate * SR)
        end = min(int((i + 1) / syllable_rate * SR), n)
        env = np.sin(np.pi * np.arange(end - start) / (end - start)) ** 0.5
        am[start:end] = env
    sig *= am
    # Normalize to target level
    peak = np.max(np.abs(sig))
    if peak > 0:
        target = 10 ** (level_dbfs / 20.0)
        sig = sig / peak * target
    return (sig * 32767).astype(np.int32)


def make_babble(duration_s: float, level_dbfs: float = -10.0) -> np.ndarray:
    """Pink-ish noise as babble approximation."""
    n = int(duration_s * SR)
    rng = np.random.default_rng(42)
    white = rng.standard_normal(n)
    # Simple pink noise via cumulative sum + normalize
    pink = np.cumsum(white) / np.arange(1, n + 1) * np.sqrt(n)
    peak = np.max(np.abs(pink))
    target = 10 ** (level_dbfs / 20.0)
    sig = pink / peak * target
    return (sig * 32767).astype(np.int32)


def make_tone_sweep(duration_s: float, f_start=200, f_end=8000) -> np.ndarray:
    """Linear frequency sweep."""
    n = int(duration_s * SR)
    t = np.arange(n) / SR
    # Log sweep
    f = f_start * (f_end / f_start) ** (t / duration_s)
    phase = 2 * np.pi * np.cumsum(f) / SR
    sig = np.sin(phase) * 0.5
    return (sig * 32767).astype(np.int32)


def make_impulse(duration_s: float) -> np.ndarray:
    n = int(duration_s * SR)
    sig = np.zeros(n, dtype=np.int32)
    sig[0] = 16000
    return sig


def assemble(mic: np.ndarray, ref: np.ndarray = None) -> np.ndarray:
    """Interleave mic (mono) and ref (mono) into 4ch: [mic1, mic2, ref1, ref2]."""
    n = len(mic)
    if ref is None:
        ref = np.zeros(n, dtype=np.int32)
    out = np.zeros((n, 4), dtype=np.int32)
    out[:, 0] = mic
    out[:, 1] = mic
    out[:, 2] = ref
    out[:, 3] = ref
    return out


def main():
    OUT_DIR.mkdir(exist_ok=True)
    print(f"Generating stimuli to {OUT_DIR}/")

    # speech_clean: 30s speech at -6 dBFS, no reference
    mic = make_speech(30, -6)
    write_wav("speech_clean.wav", assemble(mic))

    # speech_echo: speech + 40ms delayed echo in mic, echo source in ref
    speech = make_speech(30, -6)
    delay_samples = int(0.040 * SR)
    mic_echo = speech.copy()
    mic_echo[delay_samples:] += (speech[:-delay_samples] * 0.4).astype(np.int32)
    # Reference is the source that caused the echo
    ref_echo = np.zeros_like(speech)
    ref_echo[delay_samples:] = speech[:-delay_samples]
    write_wav("speech_echo.wav", assemble(mic_echo, ref_echo))

    # speech_babble: speech + babble noise at -10 dBFS, babble in ref
    speech_c = make_speech(30, -6)
    babble = make_babble(30, -10)
    mic_babble = speech_c + babble
    write_wav("speech_babble.wav", assemble(mic_babble, babble))

    # speech_quiet: speech at -36 dBFS
    write_wav("speech_quiet.wav", assemble(make_speech(30, -36)))

    # speech_loud: speech at +9 dBFS (will clip)
    n = 30 * SR
    t = np.arange(n) / SR
    sig = (
        0.5 * np.sin(2 * np.pi * 170 * t) +
        0.3 * np.sin(2 * np.pi * 220 * t) +
        0.2 * np.sin(2 * np.pi * 310 * t)
    )
    target = 10 ** (9.0 / 20.0)  # > 1.0, will clip
    sig = sig / np.max(np.abs(sig)) * target
    write_wav("speech_loud.wav", assemble((sig * 32767).astype(np.int32)))

    # silence: 2s of digital silence
    write_wav("silence.wav", silence(2))

    # noise_only: 30s babble in both mic and ref
    babble = make_babble(30, -10)
    write_wav("noise_only.wav", assemble(babble, babble))

    # tone_sweep: 10s log sweep 200Hz-8kHz
    write_wav("tone_sweep.wav", assemble(make_tone_sweep(10)))

    # impulse: 10s with single impulse at start
    write_wav("impulse.wav", assemble(make_impulse(10)))

    # barge_in: assistant speech first 5s, user speech from 5s, assistant in ref
    assistant = make_speech(15, -6)
    user = make_speech(10, -6)
    mic_bi = np.zeros(15 * SR, dtype=np.int32)
    mic_bi[:5 * SR] = assistant[:5 * SR]
    mic_bi[5 * SR:] = (assistant[5 * SR:] * 0.5 + user[:10 * SR] * 0.8).astype(np.int32)
    write_wav("barge_in.wav", assemble(mic_bi, assistant))

    # wake_word: 5s placeholder (short burst)
    ww = make_speech(5, -6)
    # Zero out everything except 1-4s
    ww_out = np.zeros_like(ww)
    ww_out[1 * SR:4 * SR] = ww[1 * SR:4 * SR]
    write_wav("wake_word.wav", assemble(ww_out))

    # commands: 20s placeholder speech
    write_wav("commands.wav", assemble(make_speech(20, -6)))

    print("Done.")


if __name__ == "__main__":
    main()
