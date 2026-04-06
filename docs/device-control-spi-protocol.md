# Device Control SPI Protocol

This document describes the SPI transport protocol currently implemented by the
device-control stack in this repository.

Primary implementation references:

- `modules/fph/rtos_device_control/transport/spi/device_control_spi.c`
- `modules/fph/rtos_device_control/src/device_control.c`
- `modules/fph/rtos_device_control/host/control_host_support.h`
- `modules/fph/rtos_device_control/host/device_access_spi_rpi.c`
- `modules/fph/rtos_device_control/api/device_control_shared.h`

## Resource ID Quick Reference

Use this table as a fast lookup for host-side command routing.

| Resource ID | Symbol | Owner |
| --- | --- | --- |
| `0` | `CONTROL_SPECIAL_RESID` | Device-control core (protocol special commands) |
| `200` | `LED_RING_SERVICER_RESID` | LED ring servicer (optional) |
| `211` | `GPIO_CONTROLLER_RESOURCE_IN_A` | GPIO servicer |
| `212` | `GPIO_CONTROLLER_RESOURCE_IN_B` | GPIO servicer |
| `221` | `GPIO_CONTROLLER_RESOURCE_OUT_A` | GPIO servicer |
| `230` | `AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID` | Audio pipeline servicer (tile 0) |
| `231` | `AUDIO_PIPELINE_SPEAKER_SETTINGS_RESID` | Audio pipeline servicer (tile 1) |
| `232` | `AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID` | Audio pipeline servicer (tile 1) |
| `240` | `DFU_CONTROLLER_SERVICER_RESID` | DFU servicer |

## Overview

Device control over SPI is a framed command protocol.

- Host sends a request header: resource ID, command ID, payload length.
- For write commands, payload bytes follow in the same transfer.
- For read commands, host typically sends an initial request transfer, then a
  second transfer to clock out the response.
- The device uses a default SPI buffer that returns
  `CONTROL_COMMAND_IGNORED_IN_DEVICE` while command processing is not yet ready.

## Command Encoding

- `resid`: 8-bit resource ID.
- `cmd`: 8-bit command. Bit 7 (`0x80`) indicates a read command.
  - Read command: `cmd & 0x80 != 0`
  - Write command: `cmd & 0x80 == 0`
- `payload_len`: 8-bit payload length in bytes.

Helper macros are defined in `device_control_shared.h`:

- `IS_CONTROL_CMD_READ(c)`
- `CONTROL_CMD_SET_READ(c)`
- `CONTROL_CMD_SET_WRITE(c)`

## Wire Format

Request frame:

| Byte offset | Field | Size |
| --- | --- | --- |
| 0 | `resid` | 1 |
| 1 | `cmd` | 1 |
| 2 | `payload_len` | 1 |
| 3.. | payload | `payload_len` |

Transaction size limits:

- SPI transfer buffers are 256 bytes on device.
- Maximum payload in this framing is 253 bytes (`256 - 3`).

Host-side helper (`control_build_spi_data()`) behavior:

- Write command frame length: `3 + payload_len`.
- Read command request length: 8 bytes (header + five zero bytes padding).

## Command Flow

### Write command flow

1. Host sends `[resid, cmd(write), payload_len, payload...]`.
2. Device validates request and forwards command to matching servicer.
3. Device stores status in `tx_buf[0]`.
4. Host performs follow-up transfer to read status.

In current SPI transport callback, when there is no response payload,
the device prepares a status frame with:

- `tx_buf[0] = 1`
- `tx_buf[1] = status`
- `tx_buf[2..] = status_buffer[]` (zero-padded remainder)

### Read command flow

1. Host sends `[resid, cmd(read), payload_len, ...]`.
2. Device records request and executes read handler.
3. Device writes read response to `tx_buf` and sets transfer response length.
4. Host performs follow-up transfer and reads response bytes.

For servicers in this firmware tree, read payload convention is:

- `payload[0]`: status
- `payload[1..]`: returned data

This status-in-payload convention is implemented by servicer read callbacks
(for example in GPIO and audio pipeline servicers), not by the SPI transport
layer itself.

## Special Resource

`CONTROL_SPECIAL_RESID` is reserved for protocol-level commands.

- `CONTROL_GET_VERSION` (`read cmd 0`): returns one byte protocol version
  (`CONTROL_VERSION`, currently `0x10`).
- `CONTROL_GET_LAST_COMMAND_STATUS` (`read cmd 1`): returns one byte status of
  last command handled by device control.

Writes to `CONTROL_SPECIAL_RESID` are rejected with `CONTROL_BAD_COMMAND`.

## NOP and Default-Buffer Behavior

NOP pattern:

- Request header bytes all zero (`0x00 0x00 0x00`) are treated as a no-op in
  SPI transfer callback.
- NOP is used by host/device flow to fetch previously prepared response bytes.

Default buffer behavior:

- During startup and in default transfer path, first TX byte is preset to
  `CONTROL_COMMAND_IGNORED_IN_DEVICE`.
- Host code retries transfers while first returned byte equals
  `CONTROL_COMMAND_IGNORED_IN_DEVICE`.

## Error Handling and Status Codes

`control_ret_t` values are defined in `device_control_shared.h`.

Common protocol and routing codes:

| Name | Value | Meaning |
| --- | --- | --- |
| `CONTROL_SUCCESS` | 0 | Command handled successfully |
| `CONTROL_REGISTRATION_FAILED` | 1 | Servicer registration failed |
| `CONTROL_BAD_COMMAND` | 2 | Unsupported command/resource command |
| `CONTROL_DATA_LENGTH_ERROR` | 3 | Payload length mismatch |
| `CONTROL_OTHER_TRANSPORT_ERROR` | 4 | Transport-level error |
| `CONTROL_BAD_RESOURCE` | 5 | Resource not registered/found |
| `CONTROL_MALFORMED_PACKET` | 6 | Packet too short or malformed |
| `CONTROL_COMMAND_IGNORED_IN_DEVICE` | 7 | Device not ready/default buffer |
| `CONTROL_ERROR` | 8 | Generic error |

Servicer-specific codes:

| Name | Value |
| --- | --- |
| `SERVICER_COMMAND_RETRY` | 64 |
| `SERVICER_WRONG_COMMAND_ID` | 65 |
| `SERVICER_WRONG_COMMAND_LEN` | 66 |
| `SERVICER_WRONG_PAYLOAD` | 67 |
| `SERVICER_QUEUE_FULL` | 68 |
| `SERVICER_SPECIAL_COMMAND_ALREADY_ONGOING` | 69 |
| `SERVICER_SPECIAL_COMMAND_BUFFER_OVERFLOW` | 70 |
| `SERVICER_RESOURCE_ERROR` | 71 |
| `SERVICER_SPECIAL_COMMAND_WRONG_ORDER` | 72 |
| `SERVICER_SPECIAL_COMMAND_BUF_SIZE_ERROR` | 73 |

## Device Status Buffer

On successful servicer registration, device control allocates an internal
status buffer (`MAX_STATUS_BUFFER_LEN = 10`) and initializes it to zero.

- SPI status-only responses include this buffer starting at `tx_buf[2]`.
- Firmware can update entries via `device_control_set_resource_status()`.
- In current application startup flow, one status slot is used as
  "device ready" indicator (index `DEVICE_STATUS_READY_REGISTER_IDX`, value
  `DEVICE_STATUS_READY_VALUE`).

On first SPI transfer after registration, the SPI transport may return a
status-only frame with `tx_buf[0]=1`, `tx_buf[1]=CONTROL_SUCCESS`, and the
current status buffer (which can still be all zeros). This lets the host
distinguish "device alive" from a physical no-response case.

## Firmware Servicers Using SPI Device Control

This section lists servicers started by firmware and reachable through the SPI
device-control protocol when `appconfDEVICE_CTRL_SPI` is enabled.

References:

- `satellite-xmos-firmware/src/main.c`
- `satellite-xmos-firmware/src/gpio/gpio_servicer.h`
- `satellite-xmos-firmware/src/gpio/gpio_cmds.h`
- `satellite-xmos-firmware/src/dfu_int/dfu_servicer.h`
- `satellite-xmos-firmware/src/dfu_int/dfu_cmds.h`
- `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_settings.h`
- `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_cmds.h`
- `satellite-xmos-firmware/src/led_ring/led_ring_servicer.h`
- `satellite-xmos-firmware/src/led_ring/led_ring_cmds.h`

### Servicer inventory

| Servicer | Source file | Resource ID(s) | Commands | Function / purpose | Gating |
| --- | --- | --- | --- | --- | --- |
| GPIO servicer | `satellite-xmos-firmware/src/gpio/gpio_servicer.c` | `211` (`GPIO_CONTROLLER_RESOURCE_IN_A`), `212` (`GPIO_CONTROLLER_RESOURCE_IN_B`), `221` (`GPIO_CONTROLLER_RESOURCE_OUT_A`) | `GPIO_CONTROLLER_SERVICER_CMD_READ_PORT` (0), `GPIO_CONTROLLER_SERVICER_CMD_WRITE_PORT` (1), `GPIO_CONTROLLER_SERVICER_CMD_SET_PIN` (2) | Read GPIO input state and drive output GPIOs through device control commands. | `appconfDEVICE_CTRL_SPI`; started on `GPIO_SERVICER_NO` tile. Board config may expose only a subset of defined GPIO resources. |
| DFU servicer | `satellite-xmos-firmware/src/dfu_int/dfu_servicer.c` | `240` (`DFU_CONTROLLER_SERVICER_RESID`) | `DFU_*` command set: detach, dnload, upload, getstatus, clrstatus, getstate, abort, setalternate, transferblock, getversion, reboot | Firmware update and DFU state-machine control over SPI device control. | `appconfDEVICE_CTRL_SPI`; task created on tile 0. |
| Audio pipeline servicer (tile 0) | `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_servicer.c` | `230` (`AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID`) | `AUDIO_PIPELINE_SETTINGS_CMD_GET_SETTINGS` (0), `AUDIO_PIPELINE_SETTINGS_CMD_SET_SETTINGS_PARTIAL` (1) | Runtime control of microphone output pipeline settings (channel map, packing, and optional ref overwrite by IC/NS outputs). | `appconfDEVICE_CTRL_SPI`; task created on tile 0. |
| Audio pipeline servicer (tile 1) | `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_servicer.c` | `231` (`AUDIO_PIPELINE_SPEAKER_SETTINGS_RESID`), `232` (`AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID`) | `AUDIO_PIPELINE_SETTINGS_CMD_GET_SETTINGS` (0), `AUDIO_PIPELINE_SETTINGS_CMD_SET_SETTINGS_PARTIAL` (1), `AUDIO_PIPELINE_SETTINGS_CMD_GET_AVAILABLE_MIC_COUNT` (2, resource `232` only) | Runtime control of mic-input gains and source-routing controls (legacy vs packaged source modes, ref/mic lane maps), runtime query of compiled mic-channel count, and control-plane storage/readback for speaker settings. | `appconfDEVICE_CTRL_SPI`; task created on `SPEAKER_PIPELINE_TILE_NO`. |
| LED ring servicer (optional) | `satellite-xmos-firmware/src/led_ring/led_ring_servicer.c` | `200` (`LED_RING_SERVICER_RESID`) | `LED_RING_SERVICER_CMD_WRITE_RAW` (0) | Write raw LED data to WS2812 LED ring. | `appconfDEVICE_CTRL_SPI && appconfLED_RING_ENABLED`; started on `WS2812_TILE_NO`. |

### Notes on availability

- The host-side device-control instance is initialized with expected servicer
  count in BSP `platform_init.c` files. A mismatch between expected and started
  servicers causes registration failure.
- Resource IDs listed above are protocol-level IDs; board/platform configuration
  can further limit which hardware-backed resources are actually meaningful at
  runtime.
- `CONTROL_SPECIAL_RESID` (`0`) is handled by device-control core logic and is
  not an application servicer.

### Mic input settings protocol (`resource 232`)

`AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID` uses the shared audio-pipeline command
IDs:

- `GET_SETTINGS` (`cmd 0`, read)
- `SET_SETTINGS_PARTIAL` (`cmd 1`, write)
- `GET_AVAILABLE_MIC_COUNT` (`cmd 2`, read)

Current payload layout (firmware branch with packaged source-routing support):

- `GET_SETTINGS` response data struct size: `16` bytes
  - `int32 mic_gain`
  - `int32 ref_gain`
  - `uint8 ref_source_mode`
  - `uint8 mic_source_mode`
  - `uint8 ref_input_channel_map[2]`
  - `uint8 mic_input_channel_map[4]`
- `SET_SETTINGS_PARTIAL` request struct size: `20` bytes
  - `uint32 field_mask`
  - `mic_input_pipeline_settings_t settings` (same field order as above)

Valid mode values:

- `ref_source_mode`:
  - `0` `AUDIO_PIPELINE_REF_SOURCE_LEGACY_DOWNSAMPLED`
  - `1` `AUDIO_PIPELINE_REF_SOURCE_PACKAGED_INPUT`
- `mic_source_mode`:
  - `0` `AUDIO_PIPELINE_MIC_SOURCE_PDM`
  - `1` `AUDIO_PIPELINE_MIC_SOURCE_PACKAGED_INPUT`

Valid lane-map index range for both arrays is `0..5`.

Mic-input partial-update mask bits:

- bit `0`: `AUDIO_PIPELINE_SETTINGS_MIC_GAIN_FIELD`
- bit `1`: `AUDIO_PIPELINE_SETTINGS_REF_GAIN_FIELD`
- bit `5`: `AUDIO_PIPELINE_SETTINGS_REF_SOURCE_MODE_FIELD`
- bit `6`: `AUDIO_PIPELINE_SETTINGS_MIC_SOURCE_MODE_FIELD`
- bit `7`: `AUDIO_PIPELINE_SETTINGS_REF_INPUT_CHANNEL_MAP_FIELD`
- bit `8`: `AUDIO_PIPELINE_SETTINGS_MIC_INPUT_CHANNEL_MAP_FIELD`

Compatibility note: this is a breaking payload-layout change for resource `232`
relative to the previous `8`/`12`-byte mic-input settings payloads.

`GET_AVAILABLE_MIC_COUNT` response payload for resource `232`:

- data size: `1` byte (`uint8_t`)
- value: `appconfMIC_PIPELINE_INPUT_CHANNELS`

## Known Constraints and Caveats

- Payload length is one byte on wire (`0..255`) and constrained further by SPI
  transfer framing (`<= 253` payload bytes).
- Current RPi host SPI path has asymmetric return semantics:
  `control_write_command()` returns device status directly, while
  `control_read_command()` copies response payload and returns `CONTROL_SUCCESS`.
- Existing `device_control_protocol.rst` in `modules/rtos` describes generic
  control protocol behavior; this document captures SPI behavior in this
  repository's active implementation.

## Minimal Examples

### Write example

Set command with 2-byte payload:

```text
Host TX #1: [resid, cmd_write, 0x02, p0, p1]
Host TX #2: [0x00, 0x00, 0x00, ...]  (clock out response)
Host RX #2: status-oriented response
```

### Read example

Read command requesting 5 response bytes (status + 4 data bytes):

```text
Host TX #1: [resid, cmd_read, 0x05, 0x00, 0x00, 0x00, 0x00, 0x00]
Host TX #2: [0x00, 0x00, 0x00, ...]  (clock out response)
Host RX #2: [status, d0, d1, d2, d3]
```
