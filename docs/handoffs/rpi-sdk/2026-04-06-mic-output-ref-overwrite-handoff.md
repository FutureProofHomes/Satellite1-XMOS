# RPi SDK Handoff

Date: 2026-04-06
Topic: mic output ref overwrite control
Firmware branch: `four_mics_sandbox`
Firmware commit(s): base `b3a8c400bddc4e7e63e232faead448aaa7011e30` plus uncommitted protocol changes in working tree

## 1) Firmware Context

- Changed files:
  - `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_settings.h`
  - `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_cmds.h`
  - `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_settings.c`
  - `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_servicer.c`
  - `satellite-xmos-firmware/audio_pipelines/reference/fixed_delay/audio_pipeline_t0.c`
  - `satellite-xmos-firmware/src/main.c`
  - `docs/device-control-command-index.md`
- Why this changed:
  - Add a firmware setting to keep the mic-output ref channels on their legacy reference content when desired instead of always overwriting them with IC/NS debug audio.
  - Preserve current behavior by default so existing deployments keep the overwrite enabled unless the host explicitly disables it.

## 2) Protocol Delta

### Resource / Command Matrix

| Resource ID | Command ID | Direction | Old | New | Notes |
|---|---:|---|---|---|---|
| `230` (`AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID`) | `0` (`GET_SETTINGS`) | read | returns pack-extra flag + channel maps | returns pack-extra flag + ref-overwrite flag + channel maps | same command id/direction |
| `230` (`AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID`) | `1` (`SET_SETTINGS_PARTIAL`) | write | partial update for pack-extra and maps | partial update for pack-extra, ref-overwrite flag, and maps | same command id/direction |

No resource IDs were added/removed.

### Payload Changes

- Response payload (resource `230`, command `GET_SETTINGS`):
  - old layout: `pack_extra_upsample_channels`, `i2s_channel_map[2]`, `upsample_channel_map[6]`
  - new layout: `pack_extra_upsample_channels`, `overwrite_ref_with_ic_ns_output`, `i2s_channel_map[2]`, `upsample_channel_map[6]`
  - new field type: `uint8`
  - expected value range: `0` or `1`
  - current documented payload size becomes `10` bytes

- Request payload (resource `230`, command `SET_SETTINGS_PARTIAL`):
  - struct size remains `16` bytes
  - new field added inside `mic_output_pipeline_settings_t`:
    - `uint8 overwrite_ref_with_ic_ns_output`
  - new field mask bit in `audio_pipeline_control_cmds.h`:
    - bit `9`: `AUDIO_PIPELINE_SETTINGS_OVERWRITE_REF_WITH_IC_NS_OUTPUT_FIELD`

### Status / Return Code Semantics

- Old behavior:
  - ref channels were always overwritten when IC/NS storage was compiled in.
  - invalid mic-output writes rejected on field-mask or channel-map validation failures.
- New behavior:
  - overwrite is conditional on `overwrite_ref_with_ic_ns_output`.
  - same status codes remain in use.
  - invalid writes now also reject `overwrite_ref_with_ic_ns_output` values outside `0` or `1`.

## 3) Compatibility

- Backward compatible: partially.
  - Default runtime behavior is backward compatible because the new field defaults to enabled (`1`).
  - Protocol layout is not fully backward compatible for SDK decoders that assume the old `GET_SETTINGS` mic-output layout.
- Expected old/new combinations:
  - old SDK against new firmware: mic-output `GET_SETTINGS` decoding may fail or misparse until the SDK learns the new field.
  - new SDK against old firmware: SDK should either gate by firmware version/payload length or tolerate the missing field.
- SDK fallback requirement:
  - decode `GET_SETTINGS` for resource `230` by payload length/version if old firmware support is still required.

## 4) Required Satellite1-RPi Updates

- Python modules to update:
  - `src/satellite1/components/xmos_device_cntrl.py`
  - `src/satellite1/sat1_hat.py`
  - `src/satellite1/cli/cli_xmos.py`
- CLI/API behavior changes:
  - extend mic-output settings model with `overwrite_ref_with_ic_ns_output`.
  - decode/encode the new mic-output field in resource `230` get/set helpers.
  - expose the field through JSON CLI payloads for `get-mic-pipeline-settings` / `set-mic-pipeline-settings` and any dedicated mic-output helpers.
- Config/env behavior changes:
  - none required.

## 5) Validation Plan

- Unit/integration tests to update/add in SDK:
  - mic-output encode/decode tests for the new resource `230` layout
  - field-mask tests covering bit `9`
  - validation tests rejecting non-boolean overwrite values
- Firmware+SDK HIL checks to run:
  - read mic-output settings and confirm the new field is present
  - write `overwrite_ref_with_ic_ns_output=0` and verify ref channels preserve legacy content
  - write `overwrite_ref_with_ic_ns_output=1` and verify IC/NS overwrite resumes

## 6) Acceptance Criteria

- [ ] SDK decodes mic-output `GET_SETTINGS` with the new field
- [ ] SDK encodes partial updates using field-mask bit `9`
- [ ] CLI JSON exposes `overwrite_ref_with_ic_ns_output`
- [ ] Invalid non-boolean overwrite writes are rejected cleanly
- [ ] HIL roundtrip and behavior checks pass against updated firmware
