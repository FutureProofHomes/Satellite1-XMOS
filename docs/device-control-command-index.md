# Device Control Command Index

Fast lookup index for SPI device-control resource and command IDs.

Use this as the first source for command-inventory questions, then spot-check the
relevant `*_cmds.h` and `*_servicer.c` files if needed.

Source references:

- `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_settings.h`
- `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_cmds.h`
- `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_servicer.c`
- `satellite-xmos-firmware/src/gpio/gpio_cmds.h`
- `satellite-xmos-firmware/src/dfu_int/dfu_cmds.h`
- `satellite-xmos-firmware/src/led_ring/led_ring_cmds.h`

## Audio Pipeline Commands

### Resource IDs

| Resource ID | Symbol | Scope |
| --- | --- | --- |
| `230` | `AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID` | Mic output settings |
| `231` | `AUDIO_PIPELINE_SPEAKER_SETTINGS_RESID` | Speaker settings |
| `232` | `AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID` | Mic input settings |

### Commands (shared across all three audio-pipeline resources)

| Command ID | Symbol | Direction | Purpose |
| --- | --- | --- | --- |
| `0` | `AUDIO_PIPELINE_SETTINGS_CMD_GET_SETTINGS` | Read | Return current active settings for the selected resource |
| `1` | `AUDIO_PIPELINE_SETTINGS_CMD_SET_SETTINGS_PARTIAL` | Write | Apply partial update via field mask and update struct |
| `2` | `AUDIO_PIPELINE_SETTINGS_CMD_GET_AVAILABLE_MIC_COUNT` | Read | Return number of mic input channels compiled into firmware (resource `232` only) |
| `3` | `AUDIO_PIPELINE_SETTINGS_CMD_GET_DOA_RAW` | Read | Return latest raw DoA estimate in mrad (resource `232` only) |
| `4` | `AUDIO_PIPELINE_SETTINGS_CMD_GET_DOA_SMOOTH` | Read | Return latest smoothed DoA estimate in mrad (resource `232` only) |
| `5` | `AUDIO_PIPELINE_SETTINGS_CMD_GET_MIC_INPUT_DEBUG_STATS` | Read | Return frame counter and per-channel mean-abs at DoA input (resource `232` only) |

### Payload shape summary

- `GET_SETTINGS` (read):
  - Mic output (`230`): `mic_output_pipeline_settings_t` (`10` bytes)
  - Speaker (`231`): `speaker_pipeline_settings_t` (`2` bytes)
  - Mic input (`232`): `mic_input_pipeline_settings_t` (`16` bytes)
- `SET_SETTINGS_PARTIAL` (write):
  - Mic output (`230`): `mic_output_pipeline_settings_update_t` (`16` bytes)
  - Speaker (`231`): `speaker_pipeline_settings_update_t` (`8` bytes)
  - Mic input (`232`): `mic_input_pipeline_settings_update_t` (`20` bytes)
- `GET_AVAILABLE_MIC_COUNT` (read, mic input resource `232` only):
  - Mic input (`232`): `uint8_t` (`1` byte), value equals `appconfMIC_PIPELINE_INPUT_CHANNELS`
- `GET_DOA_RAW` / `GET_DOA_SMOOTH` (read, mic input resource `232` only):
  - Mic input (`232`): `doa_reading_t` (`8` bytes):
    - `int32_t doa_mrad`
    - `uint16_t seq`
    - `uint8_t valid`
    - `uint8_t reserved`
- `GET_MIC_INPUT_DEBUG_STATS` (read, mic input resource `232` only):
  - Mic input (`232`): `mic_input_debug_stats_t` (`20` bytes):
    - `uint32_t frame_counter`
    - `uint32_t mic_mean_abs[4]`

- `Mic output settings` (`230`) field summary

- `pack_extra_upsample_channels` (`uint8`, `0` or `1`)
- `overwrite_ref_with_ic_ns_output` (`uint8`, `0` or `1`)
- `i2s_channel_map[2]` (`uint8[2]`, valid indices `0..7`)
- `upsample_channel_map[6]` (`uint8[6]`, valid indices `0..7`)

### Mic output partial-update mask bits (`230`, command `1`)

- bit `2`: `AUDIO_PIPELINE_SETTINGS_PACK_EXTRA_UPSAMPLE_CHANNELS_FIELD`
- bit `3`: `AUDIO_PIPELINE_SETTINGS_I2S_CHANNEL_MAP_FIELD`
- bit `4`: `AUDIO_PIPELINE_SETTINGS_UPSAMPLE_CHANNEL_MAP_FIELD`
- bit `9`: `AUDIO_PIPELINE_SETTINGS_OVERWRITE_REF_WITH_IC_NS_OUTPUT_FIELD`

### Mic input settings (`232`) field summary

- `mic_gain` (`int32`, Q2.30)
- `ref_gain` (`int32`, Q2.30)
- `ref_source_mode` (`uint8`):
  - `0` `AUDIO_PIPELINE_REF_SOURCE_LEGACY_DOWNSAMPLED`
  - `1` `AUDIO_PIPELINE_REF_SOURCE_PACKAGED_INPUT`
- `mic_source_mode` (`uint8`):
  - `0` `AUDIO_PIPELINE_MIC_SOURCE_PDM`
  - `1` `AUDIO_PIPELINE_MIC_SOURCE_PACKAGED_INPUT`
- `ref_input_channel_map[2]` (`uint8[2]`, valid indices `0..5`)
- `mic_input_channel_map[4]` (`uint8[4]`, valid indices `0..5`)

### Mic input partial-update mask bits (`232`, command `1`)

- bit `0`: `AUDIO_PIPELINE_SETTINGS_MIC_GAIN_FIELD`
- bit `1`: `AUDIO_PIPELINE_SETTINGS_REF_GAIN_FIELD`
- bit `5`: `AUDIO_PIPELINE_SETTINGS_REF_SOURCE_MODE_FIELD`
- bit `6`: `AUDIO_PIPELINE_SETTINGS_MIC_SOURCE_MODE_FIELD`
- bit `7`: `AUDIO_PIPELINE_SETTINGS_REF_INPUT_CHANNEL_MAP_FIELD`
- bit `8`: `AUDIO_PIPELINE_SETTINGS_MIC_INPUT_CHANNEL_MAP_FIELD`

## Other Servicers (quick reference)

### GPIO

- Resources: `211`, `212`, `221`
- Commands:
  - `0` `GPIO_CONTROLLER_SERVICER_CMD_READ_PORT`
  - `1` `GPIO_CONTROLLER_SERVICER_CMD_WRITE_PORT`
  - `2` `GPIO_CONTROLLER_SERVICER_CMD_SET_PIN`

### DFU

- Resource: `240`
- Commands:
  - `0` DETACH
  - `1` DNLOAD
  - `2` UPLOAD
  - `3` GETSTATUS
  - `4` CLRSTATUS
  - `5` GETSTATE
  - `6` ABORT
  - `64` SETALTERNATE
  - `65` TRANSFERBLOCK
  - `88` GETVERSION
  - `89` REBOOT

### LED ring

- Resource: `200`
- Commands:
  - `0` `LED_RING_SERVICER_CMD_WRITE_RAW`
