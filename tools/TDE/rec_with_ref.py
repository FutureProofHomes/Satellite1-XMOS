import pyaudio
import wave
import threading
import argparse

def list_audio_devices():
    """Lists all available audio devices."""
    audio = pyaudio.PyAudio()
    print("\nAvailable Audio Devices:\n")
    for i in range(audio.get_device_count()):
        device_info = audio.get_device_info_by_index(i)
        print(f"ID {device_info['index']}: {device_info['name']} - "
              f"Input Channels: {device_info['maxInputChannels']}, Output Channels: {device_info['maxOutputChannels']}")
    audio.terminate()

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

    print(f"▶️ Playing '{playback_file}' ({play_channels} channels)...")

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

    print(f"✅ Recording complete! Saved as {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simultaneously play a WAV file and record multi-channel audio.")
    parser.add_argument("-p", "--playback", type=str, required=True, help="Path to the WAV file to play")
    parser.add_argument("-o", "--output", type=str, default="recorded_audio.wav", help="Output WAV file for recording (default: recorded_audio.wav)")
    parser.add_argument("-pc", "--playback-channels", type=int, default=None, help="Number of playback channels (default: detected from WAV file)")
    parser.add_argument("-rc", "--record-channels", type=int, default=6, help="Number of recording channels (default: 6)")
    parser.add_argument("-r", "--rate", type=int, default=16000, help="Sample rate in Hz (default: 16000)")
    parser.add_argument("-b", "--chunk", type=int, default=1024, help="Buffer size (default: 1024)")
    parser.add_argument("-d", "--duration", type=int, default=10, help="Recording duration in seconds (default: 10)")
    parser.add_argument("-i", "--input-device", type=int, default=None, help="Input audio device ID (default: system default)")
    parser.add_argument("-oD", "--output-device", type=int, default=None, help="Output audio device ID (default: system default)")
    parser.add_argument("--list-devices", action="store_true", help="List available audio devices and exit")

    args = parser.parse_args()

    if args.list_devices:
        list_audio_devices()
    else:
        # Create separate threads for playback and recording
        play_thread = threading.Thread(target=play_audio, args=(args.playback, args.rate, args.chunk, args.output_device))
        record_thread = threading.Thread(target=record_audio, args=(args.output, args.record_channels, args.rate, args.chunk, args.duration, args.input_device))

        # Start both threads
        play_thread.start()
        record_thread.start()

        # Wait for both to finish
        play_thread.join()
        record_thread.join()

        print("🎵 Playback and recording completed.")
