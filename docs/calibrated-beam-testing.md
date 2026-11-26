# Calibrated pre-AEC beam: upstream integration and bench test

This branch is based on FPH `develop` at
`ace8050265f134c1e0442661c8a16866467c9e53`. The first commit adds optional
raw direction/health diagnostics; the next adds a separate `calibrated_beam`
pipeline. FPH's `fixed_delay` alias, four-mic AEC/residual averaging, fwk_voice
0.9.0 pin, protocol 0x11, flash/DFU support and release manifest are retained.
PR #132 is not applied here; it remains a separate upstream change.

The optional pipeline ports the working Tater Native XMOS 1.2.0-dev.1 signal
path: four raw microphones → calibrated steered beam plus omni channel →
2Y2X AEC with stereo echo references → IC/VNR → NS → AGC. Unlike the released
Tater Native 1.2.0-dev.1 build, this candidate enables IC/VNR. It has different
application/host glue and its own test identity; its physical observations
under FPH ESPHome are recorded in `dev4-hardware-observation.md`.

## Build the comparisons

Use XTC 15.3.1, Python 3.11, CMake and Ninja. Materialize the pinned submodules
with `git submodule update --init --recursive`. For HTTPS-only environments,
use Git's `url.https://github.com/.insteadOf=git@github.com:` configuration.
Run builds sequentially because upstream versioning writes a shared header.

```sh
bash scripts/test_doa_estimator_host.sh
bash scripts/build_directional.sh calibrated_beam
SAT1_RUN_SIM_TESTS=0 bash scripts/build_directional.sh upstream
SAT1_RUN_SIM_TESTS=0 bash scripts/build_directional.sh diagnostics
.venv/bin/python scripts/package_directional.py calibrated_beam upstream diagnostics
```

| Profile | XMOS identity | Signal path |
| --- | --- | --- |
| `upstream` | 1.2.0-dev.6 | FPH's normal four-mic AEC, unchanged; direction diagnostics off |
| `diagnostics` | 1.2.0-dev.5 | Same FPH signal path with raw direction/health telemetry |
| `calibrated_beam` | 1.2.0-dev.4 | Optional calibrated pre-AEC beam, stereo-reference 2Y2X AEC and enabled IC/VNR |

The upstream/diagnostics profiles retain FPH's 10x microphone input gain.
The calibrated-beam profile retains Tater's unity input gain. Compare signal
levels alongside acoustic results; these are different processing profiles.
All preserve the two ESP outputs: processed AGC and pre-AGC NS audio.
The package script checks linked tile identities and factory MD5 values before
writing images, checksums and a provenance manifest to `build_test/artifacts/`.
These test versions are not proposed upstream release numbers.

The installed `1.2.0-dev.4` is the selected IC-enabled candidate. An IC-bypassed
`dev.7` reference was built locally but was not installed. The tester chose
to proceed with dev.4 after hands-on voice and playback-interruption checks
and waived a controlled IC-on/off comparison. These observations do not
establish a measured improvement attributable to IC alone.

## Use FPH's ESPHome firmware

The test inputs are FPH `Satellite1-ESPHome` commit
`ef0b3d974e686c70bb4556321e1322b750eacc5c` and its pinned ESPHome 2026.10.2
(Python 3.12–3.14). Clone it under `build_test/esphome-upstream`, check out that
commit, and install its requirements in a separate Python environment.
Then generate and validate a local overlay:

```sh
.venv/bin/python scripts/prepare_esphome_test.py --profile calibrated_beam
esphome config build_test/esphome-upstream/config/satellite1.tater-calibrated_beam.yaml
esphome compile build_test/esphome-upstream/config/satellite1.tater-calibrated_beam.yaml
.venv/bin/python scripts/package_esphome_test.py --profile calibrated_beam
```

The overlay includes FPH's firmware configuration and overrides only the
bench identity and embedded XMOS image/version/checksum. Its component sources
remain unchanged. Repeat with `--profile upstream` or `--profile diagnostics`
to prepare comparison ESP images. Official host controls, buttons, LEDs and
Home Assistant API remain available. Directional LED display/control commands
are a separate host integration; this XMOS PR exposes SPI resource 233.

Package each ESPHome build before compiling the next profile: the shared
`sat1-xmos-bench` build directory is reused. Packaging checks that both host
images contain the expected XMOS binary exactly once, then preserves them
with hashes in the profile's artifact directory.

Switching from Tater Native to this FPH host requires a full USB factory flash
and FPH's partition table. Its app is larger than Tater's 3 MiB OTA slots, and
the partition layouts differ. Do not send this host image through Tater OTA.
Save the existing device flash/configuration and a Tater recovery image first.

Use a bench Sat1, retain its working recovery image and configuration, provision
the FPH firmware's Wi-Fi, and pair it with Home Assistant. Compare all profiles
using the same host settings, supply, speaker route, level and microphone
positions. Record the embedded identity and checksums for every installed image.

## Further physical qualification

- Directly record changing processed microphone samples and advancing DoA counters
  for diagnostics/beam profiles; SPI firmware identity alone is insufficient.
- Check startup, ESP-only restart, repeated cold power cycles, playback
  start/stop, silence, sustained music, wake/voice replies and barge-in.
- Compare speech from multiple directions/distances and moving talkers.
- Verify volume/mute, LED updates, AUX stereo/Both output, and recovery.

Initial physical voice observations for `dev.4` are recorded separately.
The later ESPHome companion test also confirmed direction display from opposite
sides and remembered-direction reply effects with the same XMOS image.
The full acceptance matrix remains incomplete; the controlled IC comparison
was waived by the tester. Submit the optional features for upstream review
with these limits disclosed, without changing FPH's default processing or
claiming release qualification.
