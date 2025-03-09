import pyaudio
import wave
import threading
import numpy as np

def list_audio_devices():
    """Lists all available audio devices."""
    audio = pyaudio.PyAudio()
    print("\nAvailable Audio Devices:\n")
    for i in range(audio.get_device_count()):
        device_info = audio.get_device_info_by_index(i)
        print(f"ID {device_info['index']}: {device_info['name']} - "
              f"Input Channels: {device_info['maxInputChannels']}, Output Channels: {device_info['maxOutputChannels']}")
    audio.terminate()

def get_audio_device_index(device_name:str) -> int:
    """Returns the device index for a given device name."""
    audio = pyaudio.PyAudio()
    di = None
    for i in range(audio.get_device_count()):
        device_info = audio.get_device_info_by_index(i)
        if device_info['name'].startswith(device_name):
            di = i
            break
    audio.terminate()
    return di


def play_audio(playback_file, rate, chunk, output_device):
    """Plays a WAV file using a separate thread."""
    wf = wave.open(playback_file, 'rb')
    play_channels = wf.getnchannels()
    play_rate = wf.getframerate()

    # Ensure playback rate matches file rate
    if rate != play_rate:
        print(f"⚠️ Warning: WAV file sample rate ({play_rate} Hz) differs from playback rate ({rate} Hz).")

    audio = pyaudio.PyAudio()

    # Open playback stream
    play_stream = audio.open(format=pyaudio.paInt16,
                             channels=play_channels,
                             rate=rate,
                             output=True,
                             output_device_index=output_device,
                             frames_per_buffer=chunk)

    print(f"Playing '{playback_file}' ({play_channels} channels)...")

    while True:
        data = wf.readframes(chunk)
        if not data:
            break
        play_stream.write(data)

    # Cleanup
    wf.close()
    play_stream.stop_stream()
    play_stream.close()
    audio.terminate()
    print("🔇 Playback finished.")

def record_audio(output_file, channels, rate, chunk, duration, input_device):
    """Records multi-channel audio in a separate thread."""
    
    FORMAT = pyaudio.paInt16  # 16-bit PCM
    audio = pyaudio.PyAudio()

    # Open recording stream
    record_stream = audio.open(format=FORMAT,
                               channels=channels,
                               rate=rate,
                               input=True,
                               input_device_index=input_device,
                               frames_per_buffer=chunk)

    print(f"🎤 Recording {channels} channels at {rate} Hz for {duration} seconds...")

    frames = []
    for _ in range(0, int(rate / chunk * duration)):
        data = record_stream.read(chunk, exception_on_overflow=False)
        frames.append(data)

    # Cleanup
    record_stream.stop_stream()
    record_stream.close()
    audio.terminate()

    # Save recorded audio
    with wave.open(output_file, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(audio.get_sample_size(FORMAT))
        wf.setframerate(rate)
        wf.writeframes(b''.join(frames))

    print(f"Recording complete! Saved as {output_file}")


class ThreadWithException(threading.Thread):

    def run(self):
        self.exc = None  # Store exception here
        try:
            print("Thread running...")
            super().run()
        except Exception as e:
            self.exc = e  # Store the exception

def run_playback_and_record( play_file:str, out_device:int, rec_file:str, in_device:int, duration:int  ):
    # Create separate threads for playback and recording
    play_thread = ThreadWithException(target=play_audio, args=(play_file, 16000, 1024, out_device))
    record_thread = ThreadWithException(target=record_audio, args=(rec_file, 6, 16000, 1024, duration, in_device))

    # Start both threads
    play_thread.start()
    record_thread.start()

    # Wait for both to finish
    play_thread.join()
    record_thread.join()
    if play_thread.exc:
        print(f"Exception in thread: {play_thread.exc}")
        raise play_thread.exc  # Optionally re-raise it in the main thread
   
    if record_thread.exc:
        print(f"Exception in thread: {record_thread.exc}")
        raise record_thread.exc  # Optionally re-raise it in the main thread
    
    print("🎵 Playback and recording completed.")


def read_wav_wave(filename):
    """
    Read a WAV file using the `wave` module and return its data as a NumPy array.

    Parameters:
        filename (str): Path to the WAV file.

    Returns:
        fs (int): Sampling rate in Hz.
        audio_data (numpy array): Audio data with shape (Samples, Channels).
    """
    with wave.open(filename, "rb") as wf:
        num_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        fs = wf.getframerate()
        num_frames = wf.getnframes()
        
        print("\n")
        print(f"Reading '{filename}'...")
        print(f"Channels: {num_channels}, Sample Width: {sample_width} bytes, Sample Rate: {fs} Hz, Frames: {num_frames}")

        # Read raw audio data
        raw_data = wf.readframes(num_frames)

        # Convert raw bytes to NumPy array
        audio_data = np.frombuffer(raw_data, dtype=np.int16)  # 16-bit PCM

        # Reshape if multichannel
        if num_channels > 1:
           audio_data = audio_data.reshape(-1, num_channels)

        return fs, audio_data