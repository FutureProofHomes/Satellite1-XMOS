import numpy as np
from silero_vad import load_silero_vad, get_speech_timestamps
from orbit.audio.utils import read_wav_wave

def vad_silero(wav_file:str=None, channel:int=0, audio:np.array=None) -> list[dict]:
    vad = load_silero_vad()
    if wav_file:
        fs, audio = read_wav_wave(wav_file)
        if fs != 16000:
            raise ValueError("Only 16kHz audio is supported.")
        if  audio.shape[1] > 1:
            audio = audio[:, channel]
    elif audio is None:
        raise ValueError("Either wav_file or audio must be provided.")

    speech_timestamps = get_speech_timestamps(
        audio,
        vad,
    return_seconds=True,  # Return speech timestamps in seconds (default is samples)
    )
    
    return speech_timestamps