# Add optional four-mic speech tracking and fix DSP transport stalls

This PR adds an optional four-microphone speech-tracking pipeline for Satellite1 and fixes a communication lock cycle that could stall audio during startup or playback.

### What’s included

- **Four-microphone echo cancellation** before speech-aware direction tracking and calibrated beamforming.
- **Protected interference and residual-echo cleanup**, followed by noise suppression and gain control.
- **Direction finding, microphone calibration and health telemetry** for the companion ESPHome direction animations.
- **Separate DSP communication** from I2S/GPIO control, with bounded audio buffering.
- **Capability-gated playback/listening hints** that expire automatically if the host stops refreshing them.

FPH’s existing pipeline, default release selection and both ESP32 audio outputs are preserved. The earlier calibrated-beam/two-channel AEC target remains available. Existing telemetry packet layouts and manual steering controls remain compatible.

### Helper scripts

Build and package the new pipeline from the XMOS checkout:

```sh
bash scripts/build_directional.sh speech_tracking
.venv/bin/python scripts/package_directional.py speech_tracking
```

Verified artifacts are written to `build_test/artifacts/`. Other supported profiles are `calibrated_beam`, `diagnostics` and `upstream`. Build profiles sequentially.

From the companion [ESPHome PR #622](https://github.com/FutureProofHomes/Satellite1-ESPHome/pull/622) checkout, generate and install a paired test build:

```sh
.venv/bin/python scripts/prepare_speech_tracking_test.py \
  --xmos-artifacts /path/to/Satellite1-XMOS/build_test/artifacts

.venv/bin/python -m esphome run \
  config/satellite1.speech-tracking-test.yaml --no-logs
```

The helper verifies the XMOS artifacts and generates a configuration containing the matching image, version and checksum. ESPHome installs that XMOS image automatically when needed.

### ESPHome integration

The companion PR provides directional listening/reply animations and enables playback/listening hints by default. Hints work independently of the LED switch and are sent only after XMOS advertises support. Setting `xmos_audio_hints: "false"` disables hint probes and writes.

The standard ESPHome configuration retains its existing XMOS image selection; the generated test configuration selects the new pipeline.

Related: [issue #129](https://github.com/FutureProofHomes/Satellite1-XMOS/issues/129).
