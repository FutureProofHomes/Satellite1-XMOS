# RPi SDK Handoff

Date: 2026-03-27
Topic: mic input routing modes + packaged source maps
Firmware branch: `audio_pipeline_control_servicer`
Firmware commit(s): base `e6bb662` plus uncommitted protocol changes in working tree

## 1) Firmware Context

- Changed files:
  - `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_settings.h`
  - `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_cmds.h`
  - `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_settings.c`
  - `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_servicer.c`
  - `satellite-xmos-firmware/src/main.c`
- Why this changed:
  - Add SPI-controllable source selection so mic pipeline inputs can use live PDM or packaged I2S lanes, and AEC ref can use legacy downsampled path or packaged lanes.
  - Enforce mirrored DAC behavior in packaged ref mode.

## 2) Protocol Delta

### Resource / Command Matrix

| Resource ID | Command ID | Direction | Old | New | Notes |
|---|---:|---|---|---|---|
| `232` (`AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID`) | `0` (`GET_SETTINGS`) | read | returns gains only | returns gains + source modes + lane maps | same command id/direction |
| `232` (`AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID`) | `1` (`SET_SETTINGS_PARTIAL`) | write | partial update for gain fields | partial update for gain + mode + map fields | same command id/direction |
| `232` (`AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID`) | `2` (`GET_AVAILABLE_MIC_COUNT`) | read | n/a | returns compiled mic input channel count (`uint8`) | new command id |

No resource IDs were added/removed.

### Payload Changes

- Request payload (old -> new), resource `232`, command `SET_SETTINGS_PARTIAL`:
  - old size: `12` bytes (`field_mask` + `mic_gain` + `ref_gain`)
  - new size: `20` bytes (`field_mask` + expanded `mic_input_pipeline_settings_t`)
  - new settings fields appended:
    - `uint8 ref_source_mode`
    - `uint8 mic_source_mode`
    - `uint8 ref_input_channel_map[2]`
    - `uint8 mic_input_channel_map[4]`
  - field masks added in `audio_pipeline_control_cmds.h`:
    - bit 5: `AUDIO_PIPELINE_SETTINGS_REF_SOURCE_MODE_FIELD`
    - bit 6: `AUDIO_PIPELINE_SETTINGS_MIC_SOURCE_MODE_FIELD`
    - bit 7: `AUDIO_PIPELINE_SETTINGS_REF_INPUT_CHANNEL_MAP_FIELD`
    - bit 8: `AUDIO_PIPELINE_SETTINGS_MIC_INPUT_CHANNEL_MAP_FIELD`

- Response payload (old -> new), resource `232`, command `GET_SETTINGS`:
  - old size: `8` bytes (`mic_gain`, `ref_gain`)
  - new size: `16` bytes (expanded settings struct)
  - status-byte convention unchanged (`payload[0]` status in servicer read path)

- Response payload, resource `232`, command `GET_AVAILABLE_MIC_COUNT`:
  - size: `1` byte (`uint8`)
  - value: `appconfMIC_PIPELINE_INPUT_CHANNELS`

### Status / Return Code Semantics

- Old behavior:
  - `SERVICER_WRONG_PAYLOAD` on invalid map/field mask/length.
- New behavior:
  - same status codes, expanded validation to include mode enums and packaged lane-map bounds.
- Error conditions:
  - new map fields reject indices outside `0..5`.
  - mode fields reject values outside enum ranges.

## 3) Compatibility

- Backward compatible: no (breaking payload size/layout change on existing resource `232`).
- Required SDK fallback behavior:
  - none required if firmware+SDK are upgraded together.
  - old SDK against new firmware will fail on `SET_SETTINGS_PARTIAL` length validation for resource `232`.
- Runtime detection strategy (if needed):
  - probe firmware version and branch behavior in SDK, or attempt `GET_SETTINGS` and branch by returned payload length.
  - `GET_AVAILABLE_MIC_COUNT` can be used by SDK/CLI to adapt mic routing UX to firmware build-time mic count.

## 4) Required Satellite1-RPi Updates

- Python modules to update:
  - `src/satellite1/components/xmos_device_cntrl.py`
  - `src/satellite1/sat1_hat.py`
  - `src/satellite1/cli/cli_xmos.py` (if exposing CLI controls)
- CLI/API behavior changes:
  - extend mic-input settings dataclass/model with:
    - `ref_source_mode`
    - `mic_source_mode`
    - `ref_input_channel_map[2]`
    - `mic_input_channel_map[4]`
  - extend partial-update encoder to support new field masks.
  - decode GET payload with new size/layout.
  - add read helper/API for command `2` to expose available mic count.
- Config/env behavior changes:
  - none required.

## 5) Validation Plan

- Unit/integration tests to update/add in SDK:
  - encoder/decoder tests for resource `232` old/new layout assumptions (new layout required)
  - field-mask tests for new mode/map bits
  - bounds checks for lane maps (`0..5`) and enum values
  - decode/read test for command `GET_AVAILABLE_MIC_COUNT` returning `uint8`
- HIL checks to run:
  - read/write roundtrip for new mic-input fields via SDK
  - switch `mic_source_mode` between live and packaged and verify behavior transitions
  - switch `ref_source_mode` between legacy and packaged and verify mirror behavior at DAC + mic ref path

## 6) Acceptance Criteria

- [ ] SDK `GET_SETTINGS`/`SET_SETTINGS_PARTIAL` for resource `232` works with new payload sizes
- [ ] SDK `GET_AVAILABLE_MIC_COUNT` command works and drives mic-count-aware UX
- [ ] New mode/map fields are encoded/decoded correctly
- [ ] Invalid mode/map writes are rejected as expected
- [ ] SQ66 HIL checks pass with updated SDK against updated firmware
