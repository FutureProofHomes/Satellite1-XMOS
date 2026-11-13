"""Audio metric functions for DSP pipeline testing."""
import numpy as np
from scipy.signal import stft
from scipy.io import wavfile


def rms_db(signal):
    """RMS level in dBFS (full scale = 32768 for int32, 1.0 for float)."""
    if signal.dtype in (np.int32, np.int16):
        signal = signal.astype(np.float64)
        full_scale = 2 ** (signal.dtype.itemsize * 8 - 1) if signal.dtype == np.int32 else 32768
        signal = signal / full_scale
    rms = np.sqrt(np.mean(signal ** 2))
    if rms == 0:
        return -np.inf
    return 20 * np.log10(rms)


def snr_db(signal, noise):
    """Signal-to-noise ratio in dB."""
    sig_power = np.mean(signal ** 2)
    noise_power = np.mean(noise ** 2)
    if noise_power == 0:
        return np.inf
    if sig_power == 0:
        return -np.inf
    return 10 * np.log10(sig_power / noise_power)


def aec_residual_db(mic_out, ref, skip_frames=10):
    """AEC residual echo level in dB.

    Measures how much reference energy remains in the mic output after AEC.
    Lower (more negative) = better cancellation.
    skip_frames: number of 240-sample frames to skip for convergence.
    """
    skip = skip_frames * 240
    mic_seg = mic_out[skip:]
    ref_seg = ref[skip:]
    n = min(len(mic_seg), len(ref_seg))
    mic_seg = mic_seg[:n]
    ref_seg = ref_seg[:n]

    if np.max(np.abs(ref_seg)) == 0:
        return -np.inf

    # Cross-correlation based residual: project mic onto ref
    ref_power = np.sum(ref_seg ** 2)
    if ref_power == 0:
        return -np.inf
    correlation = np.sum(mic_seg * ref_seg) / ref_power
    residual = mic_seg - correlation * ref_seg
    residual_power = np.mean(residual ** 2)
    ref_rms = np.sqrt(np.mean(ref_seg ** 2))
    if ref_rms == 0:
        return -np.inf
    return 20 * np.log10(np.sqrt(residual_power) / ref_rms + 1e-12)


def ns_snr_improvement_db(mic_in, mic_out, ref_speech):
    """NS SNR improvement in dB.

    Compares SNR before and after noise suppression.
    """
    n = min(len(mic_in), len(mic_out), len(ref_speech))
    mic_in = mic_in[:n]
    mic_out = mic_out[:n]
    ref_speech = ref_speech[:n]

    noise_in = mic_in - ref_speech
    noise_out = mic_out - ref_speech

    snr_before = snr_db(ref_speech, noise_in)
    snr_after = snr_db(ref_speech, noise_out)

    if np.isinf(snr_before) or np.isinf(snr_after):
        return 0.0
    return snr_after - snr_before


def agc_output_level_db(signal, skip_frames=20):
    """AGC output level in dBFS after convergence."""
    skip = skip_frames * 240
    if len(signal) <= skip:
        return rms_db(signal)
    return rms_db(signal[skip:])


def _mel_filterbank(sr=16000, n_mels=26, n_fft=512, fmin=0, fmax=8000):
    """Create a Mel filterbank."""
    def hz_to_mel(f):
        return 2595 * np.log10(1 + f / 700)

    def mel_to_hz(m):
        return 700 * (10 ** (m / 2595) - 1)

    mel_min = hz_to_mel(fmin)
    mel_max = hz_to_mel(fmax)
    mel_points = np.linspace(mel_min, mel_max, n_mels + 2)
    hz_points = mel_to_hz(mel_points)

    bins = np.floor((n_fft + 1) * hz_points / sr).astype(int)
    fbank = np.zeros((n_mels, n_fft // 2 + 1))

    for i in range(n_mels):
        left, center, right = bins[i], bins[i + 1], bins[i + 2]
        for j in range(left, center):
            if center != left:
                fbank[i, j] = (j - left) / (center - left)
        for j in range(center, right):
            if right != center:
                fbank[i, j] = (right - j) / (right - center)

    return fbank


def log_mel_distance(sig_a, sig_b, sr=16000, n_mels=26, n_fft=512):
    """Mean log-mel spectral distance between two signals in dB.

    0 = identical spectra, higher = more different.
    """
    n = min(len(sig_a), len(sig_b))
    sig_a = sig_a[:n]
    sig_b = sig_b[:n]

    fbank = _mel_filterbank(sr, n_mels, n_fft)

    def log_mel_features(sig):
        zxx, _, _ = stft(sig, fs=sr, nperseg=n_fft, noverlap=n_fft // 2)
        power = np.abs(zxx) ** 2
        mel = fbank @ power.T
        return np.log(mel + 1e-10)

    feat_a = log_mel_features(sig_a)
    feat_b = log_mel_features(sig_b)

    # Convert log to dB scale for interpretable distance
    diff = feat_a - feat_b
    return float(np.mean(np.abs(diff)) * 20 / np.log(10))


def pesq_score(reference, degraded, sr=16000):
    """PESQ quality score (1.0-4.5). Returns None if pesq not available."""
    try:
        from pesq import pesq as pesq_fn
        # PESQ requires 16-bit PCM, 8 kHz or 16 kHz
        ref_16 = (reference * 32767).astype(np.int16)
        deg_16 = (degraded * 32767).astype(np.int16)
        return float(pesq_fn(sr, ref_16, deg_16))
    except ImportError:
        return None


def spectral_flatness(signal, n_fft=512):
    """Spectral flatness: 0 = tonal, 1 = noise-like."""
    n_frames = max(1, len(signal) // n_fft)
    flatness_values = []
    for i in range(n_frames):
        frame = signal[i * n_fft:(i + 1) * n_fft]
        spectrum = np.abs(np.fft.rfft(frame * np.hanning(len(frame))))
        spectrum = spectrum[spectrum > 0]
        if len(spectrum) == 0:
            continue
        geometric_mean = np.exp(np.mean(np.log(spectrum + 1e-10)))
        arithmetic_mean = np.mean(spectrum)
        if arithmetic_mean > 0:
            flatness_values.append(geometric_mean / arithmetic_mean)
    if not flatness_values:
        return 0.0
    return float(np.mean(flatness_values))


def clipping_ratio(signal):
    """Fraction of samples that are clipped (at or near full scale)."""
    if signal.dtype in (np.int32, np.int16):
        full_scale = 2 ** (signal.dtype.itemsize * 8 - 1) - 1
        return float(np.mean(np.abs(signal) >= full_scale * 0.999))
    return float(np.mean(np.abs(signal) >= 0.999))


def peak_to_rms_ratio(signal):
    """Crest factor: peak/RMS ratio."""
    peak = np.max(np.abs(signal))
    rms = np.sqrt(np.mean(signal ** 2))
    if rms == 0:
        return 0.0
    return float(peak / rms)
