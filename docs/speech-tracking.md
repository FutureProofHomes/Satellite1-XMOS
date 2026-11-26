# Optional post-AEC speech tracking profile

`satellite1_firmware_speech_tracking` is an explicit alternative to FPH's
existing pipeline and the earlier `calibrated_beam` target. It does not change
`firmware_version.txt`, the `fixed_delay` alias, the release target selection or
ESPHome's default XMOS image/version/URLs.

## Processing and transport

Four raw microphones supply health and gain calibration on tile 1. AEC operates
on each microphone with the stereo playback reference mixed to mono. The same
frame carries its raw calibration to tile 0, where VNR speech evidence gates
direction tracking and a calibrated fractional-delay beam. Microphone exclusion
and calibration are not retrained from AEC residual levels.

The beam also produces a blocking reference for interference cancellation.
IC adapts on nonspeech while steering is settled; movement briefly bypasses it.
During speech its cancellation estimate is bounded to protect the primary
signal. Bypass and cleanup paths match IC's 600-sample primary delay plus
32-sample WOLA delay (39.5 ms at 16 kHz). Nonspeech correlated with playback can
be gradually attenuated to half gain. NS and AGC follow using the frame's speech
evidence. VNR inference has one owner and never runs concurrently in IC.

The beam uses the bit-exact fractional-delay arithmetic optimized in Tater
Native. This profile retains unity raw microphone gain, like `calibrated_beam`;
FPH's existing pipeline retains its existing 10x gain. The two ESP audio outputs
remain processed AGC and pre-AGC noise-suppressed audio, at the existing rates.
This profile does not add dedicated dereverberation or stereo-reference 4Y2X AEC.

Blocking DSP frame transfers now use a separate intertile context from I2S/GPIO
RPC across the supported pipelines. Previously an audio send could hold the RPC
lock while its receiver waited for an I2S response on that same lock. The
speaker passthrough uses one stage and a one-entry reference queue to bound
live frame storage. The new profile also captures directly into an aligned,
compact frame; generic_pipeline frees each dynamically allocated frame once.

## Host hints and compatible telemetry

Existing resource 233 READ_STATE (32 bytes), READ_DIAGNOSTICS (48 bytes), and
SET_CONTROL commands retain their layouts. The new profile publishes direction
observations separately from audio-only steering fallback, preserving display
direction while audio policy requests a wide beam. Older profiles retain their
original state publication.

READ_CAPABILITIES is command 3 (read request 0x83), returning eight bytes:

| Offset | Value |
| --- | --- |
| 0–3 | `S`, `1`, `D`, protocol version `1` |
| 4–7 | little-endian uint32 feature flags; bit 0 means host hints supported |

Only `speech_tracking` advertises host hints. Old images may reject the command;
new builds of the older profiles return zero flags. A host must verify the
signature/version/capability before sending hints.

SET_HOST_HINTS (write command 4, one byte) bit 0 means playback is active;
bit 3 means the host is listening to
a confirmed voice request. These indications help the new tracker avoid
following its speaker while allowing an established user session to continue
tracking over playback. They do not start/end a voice request or change audio
samples, wake detection, speech timeouts, ducking or volume.

The separate hint command preserves existing manual force-omni and lock bits;
it does not replace SET_CONTROL. A heartbeat once per second refreshes the hints. In the new frontend they expire
after 160 advancing DSP frames (about 2.4 seconds of processing) without an
update. Legacy force-omni/lock controls keep their persistent semantics.
The core AEC/frontend can run without a hint-capable host; complete host-assisted
behavior still requires testing the paired firmware.

## Local build and paired test

Build profiles sequentially because version generation writes a shared header:

```sh
bash scripts/build_directional.sh speech_tracking
.venv/bin/python scripts/package_directional.py speech_tracking
```

The helper assigns this experimental profile `v1.2.0-dev.16`. Rebuilt comparison
profiles use dev.17 (`calibrated_beam`), dev.18 (`diagnostics`) and dev.19
(`upstream`) so they cannot be mistaken for the earlier tested dev.4–dev.6
images. These are test identities; FPH's normal version selection is unchanged.
Artifacts and verified linked identities/checksums are in
`build_test/artifacts/manifest.json`.

In the companion ESPHome checkout:

```sh
.venv/bin/python scripts/prepare_speech_tracking_test.py \
  --xmos-artifacts /path/to/Satellite1-XMOS/build_test/artifacts
.venv/bin/python -m esphome compile config/satellite1.speech-tracking-test.yaml
```

The generated, ignored YAML selects only the verified local test image and
sets `xmos_audio_hints: "true"`, which is also the shared ESPHome configuration's
default. Hints start automatically only after an explicit supporting capability
response; unsupported images receive bounded capability probes and no hint
writes. Set the substitution to `"false"` to disable all hint probes and writes.
The normal configuration still selects FPH's existing XMOS image. Hints operate
independently of the optional LED switch, with independent ownership of read-only
PCM metering.

## Prepared test image

The locally packaged `v1.2.0-dev.16` factory image is 245,760 bytes, SHA-256
`0a65be7f15bba90c9d562e69136ec7f2087a1a70f16557517288599fed687a73`.
Linked ELF identities and factory MD5/SHA-256 were verified for all four
profiles. The paired ESPHome OTA was checked to contain this exact payload once;
the normal ESPHome OTA does not contain it. Host hints are enabled by default,
while only the opt-in build selects this new DSP image. The artifact manifest
keeps hardware validation pending.

## Evidence and remaining hardware checks

The algorithm and transport changes were exercised on one Satellite1 running
Tater Native, including reboot recovery, audible playback, immediate commands
from two sides and direction LEDs during music. They are the basis for this
port; that native firmware's hardware observations do not qualify the new FPH
binary or its ESPHome integration. Historical dev.4 ESPHome observations in
`dev4-hardware-observation.md` apply only to the older pre-AEC beam image.

Local software checks include all four firmware profile builds, host direction,
beam and hint-lease tests, legacy/new-profile host/XS3A transport contracts,
capability/telemetry serialization, and a real-library frontend simulator for
AEC/VNR/beam/IC/NS/AGC, repeated initialization and IC bypass alignment.
The companion default and opt-in ESPHome builds are checked separately.
The real-library simulator passed 24 frames across two initializations. IC
protected bypass matched the actual IC delay within one LSB; the maximum
combined postprocessing time was 13.40819 ms against a 15 ms frame interval.
These simulator results do not substitute for the paired hardware checks.

Before hardware qualification, test the new pair for cold boots, quiet and
music wake/commands from two sides, talking while moving, immediate post-wake
LED direction, reply animation, LED-switch toggling, mute/unmute, playback
interruptions and return to music. Check the existing FPH image's fallback too.
Far-field accuracy, moving-talker gains, ERLE and false-wake rates have not been
quantified. No fresh FPH hardware pass or fresh public CI result is claimed.
