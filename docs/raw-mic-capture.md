# Recording all four Satellite1 microphones over USB

`satellite1_usb_firmware_raw_capture` is a development image. It records
four mic channels and the stereo speaker feed together as **16 kHz signed
32-bit PCM**, with no mic gain, AEC, IC, NS, or AGC. The mic samples have
already been converted from PDM to PCM by the mic driver.

| WAV channel (1-based) | Signal | PDM input |
|---|---|---|
| 1 | Mic 0 (East) | 4 |
| 2 | Mic 1 (West) | 5 |
| 3 | Mic 2 (North) | 0 |
| 4 | Mic 3 (South) | 1 |
| 5 | Speaker reference, left | — |
| 6 | Speaker reference, right | — |

Verify the directional labels on your board by tapping or speaking close to
each mic in turn. The reference is the digital feed queued for the speaker,
not an acoustic loopback. Expect a playback-to-mic delay, including buffering
and acoustic travel time; measure it from the recording before tuning AEC.

## Build and flash

With the XMOS tools active and the normal build dependencies installed:

```sh
cmake -B build-capture --toolchain xmos_cmake_toolchain/xs3a.cmake
cmake --build build-capture --target create_flash_img_satellite1_usb_firmware_raw_capture
```

Alternatively, build from the repository root with rootless Podman and the
same builder image used by CI (`ghcr.io/xmos/xcore_builder:v3.1`, XTC 15.3.0).
This does not require `xcc` on the host:

```sh
podman run --rm --userns=keep-id -v "$PWD:/ws" -w /ws \
  ghcr.io/xmos/xcore_builder:v3.1 bash -lc '
    cmake -B build/raw-capture-podman --toolchain xmos_cmake_toolchain/xs3a.cmake &&
    cmake --build build/raw-capture-podman \
      --target create_flash_img_satellite1_usb_firmware_raw_capture
  '
```

Use the [normal XMOS flash procedure](../README.md) with the capture image.
This image is not for Assist: it does not send mic audio to the ESP32. Keep
the normal image handy to restore afterwards, and disable ESPHome's XMOS
auto-flash if it is enabled in your configuration.

## Record while playing music

On Linux, install ALSA utilities (`alsa-utils` on Debian/Ubuntu) and FFmpeg.
Connect the board's XMOS USB port to the PC with a **data** cable, and make
sure a speaker is connected to the Satellite1. Run `arecord -l` and `aplay -l`
to find its capture and playback devices. For example, `card 2, device 0`
becomes `hw:2,0`. Substitute the actual values for `CARD,DEV` in each command;
the capture and playback device numbers need not match.

Prepare a short clip from a local music or podcast file. The USB playback
endpoint expects stereo 16 kHz, 32-bit PCM. This example starts with reduced
playback volume:

```sh
ffmpeg -i music.mp3 -t 15 -vn -af volume=-12dB -ac 2 -ar 16000 \
  -c:a pcm_s32le playback.wav
```

In terminal 1, start capture:

```sh
arecord -D hw:CARD,DEV -t wav -f S32_LE -r 16000 -c 6 -d 30 capture.wav
```

A few seconds later, in terminal 2, play the clip **through the Satellite1**,
not the PC speakers:

```sh
aplay -D hw:CARD,DEV playback.wav
```

Let the speaker play by itself for a few seconds, then speak over it. Keep
speaking after the clip ends. That gives you playback-only, speech over
playback, and speech-only in one take. Use `hw:` to avoid desktop audio
remixing or gain on capture. If ALSA reports `Device or resource busy`, close
other apps using the device.

Check the recording before collecting more takes:

```sh
ffprobe -v error -select_streams a:0 \
  -show_entries stream=codec_name,sample_rate,channels,duration \
  -of default=noprint_wrappers=1 capture.wav
```

Expect `pcm_s32le`, `16000`, `6`, and roughly `30` seconds. Channels 5 and 6
should contain the music during playback; channels 1–4 should contain the
room sound and your voice. If the reference lanes stay silent, verify that
`aplay` is using the Satellite1 playback endpoint. Record a separate take
without music to test beamforming and noise suppression independently.

## Listen to and analyze individual channels

[Audacity](https://www.audacityteam.org/) is a free multitrack editor for
Linux, macOS, and Windows. For predictable track names and ordering, split
the capture into six mono copies first. This POSIX shell example uses FFmpeg
to copy each channel without remixing or normalizing it:

```sh
channel=0
for name in mic0-east mic1-west mic2-north mic3-south ref-left ref-right; do
  ffmpeg -n -i capture.wav -af "pan=mono|c0=c${channel}" \
    -c:a pcm_s32le "${name}.wav" || break
  channel=$((channel + 1))
done
```

In Audacity, use **File → Import → Audio** and select all six mono files
together. They start at the same point on the timeline.

- **Listen:** use **Solo** on one track or **Mute** to exclude tracks.
  To compare a mic against a reference, mute the other four tracks.
- **Inspect timing:** expand the tracks and zoom in on the same playback
  onset. Compare `ref-left` or `ref-right` with a mic waveform.
- **Inspect frequency content:** change a track's display to **Spectrogram**,
  or select a time range on one track and use **Analyze → Plot Spectrum**.

Keep `capture.wav` unchanged for offline DSP. Treat Audacity tracks and
exports as listening or analysis copies; don't normalize the individual
channels before comparing mic levels or running AEC.

## Replay offline

Keep the six-channel WAV as the source of truth. Use channels 1–4 for
beamforming and 5–6 as the AEC reference. No amplitude correction is
needed. A two-mic/two-reference runner needs a copy containing only channels
1, 2, 5, and 6, in that order. Replay each variant from the beginning so
adaptive filters get the same lead-in; send their mono output to STT.

USB startup may contain silence. If the firmware log reports `Raw capture:
dropped blocks`, `Raw capture: padded packets`, or `mic rx overrun` during
the take, repeat it before relying on sample timing.
