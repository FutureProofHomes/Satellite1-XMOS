from orbit.audio.utils import read_wav_wave
import numpy as np
from scipy.signal import correlate

def calc_channel_variances( wav_file:str ) -> list[float]:
    fs, audio_data = read_wav_wave(wav_file)
    return audio_data.var(axis=0)


def estimate_time_delay(reference_signal, delayed_signal, fs):
    """
    Estimate time delay using cross-correlation.

    Parameters:
        reference_signal (numpy array): Original signal.
        delayed_signal (numpy array): Delayed version of the signal.
        fs (int): Sampling rate in Hz.

    Returns:
        estimated_delay_sec (float): Estimated delay in seconds.
    """
    correlation = correlate(delayed_signal, reference_signal, mode="full")
    delay_samples = np.argmax(correlation) - len(reference_signal) + 1
    estimated_delay_sec = delay_samples / fs
    
    return estimated_delay_sec, correlation