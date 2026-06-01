# Device Control SPI Protocol

This document describes the SPI transport protocol implemented by the
device-control stack in this repository for `CONTROL_VERSION 0x11`.

Primary implementation references:

- `modules/fph/rtos_device_control/api/device_control_shared.h`
- `modules/fph/rtos_device_control/transport/spi/device_control_spi.c`
- `modules/fph/rtos_device_control/src/device_control.c`
- `modules/fph/rtos_device_control/src/resource_table.c`
- `modules/fph/rtos_device_control/host/control_host_support.h`
- `modules/fph/rtos_device_control/host/device_access_spi_rpi.c`

## Protocol Version

`CONTROL_VERSION` is `0x11`.

The protocol version is returned by reading `CONTROL_GET_VERSION` from
`CONTROL_SPECIAL_RESID`.

## Resource ID Quick Reference

| Resource ID | Symbol | Owner | Current Satellite1 registration |
| --- | --- | --- | --- |
| `0` | `CONTROL_SPECIAL_RESID` | Device-control core | Always handled specially |
| `200` | `LED_RING_SERVICER_RESID` | LED ring servicer | Registered when SPI device control is enabled and the WS2812 tile starts the servicer |
| `211` | `GPIO_CONTROLLER_RESOURCE_IN_A` | GPIO servicer | Registered by current Satellite1 board config |
| `212` | `GPIO_CONTROLLER_RESOURCE_IN_B` | GPIO servicer | Defined, but not registered by current Satellite1 board config |
| `221` | `GPIO_CONTROLLER_RESOURCE_OUT_A` | GPIO servicer | Defined, but not registered by current Satellite1 board config |
| `240` | `DFU_CONTROLLER_SERVICER_RESID` | DFU servicer | Registered when SPI device control is enabled |

The current Satellite1 board config initializes two GPIO resource descriptors but
passes `1` to `gpio_servicer_init()`, so only `GPIO_CONTROLLER_RESOURCE_IN_A`
is registered.

## Command Encoding

- `resid`: 8-bit resource ID.
- `cmd`: 8-bit command ID.
- `payload_len`: 8-bit payload length in bytes.
- Command bit 7 (`0x80`) indicates a read command.
- Write command: `cmd & 0x80 == 0`.
- Read command: `cmd & 0x80 != 0`.

Helper macros are defined in `device_control_shared.h`:

- `IS_CONTROL_CMD_READ(c)`
- `CONTROL_CMD_SET_READ(c)`
- `CONTROL_CMD_SET_WRITE(c)`

## Request Wire Format

Each non-NOP request starts with a three-byte header.

| Byte offset | Field | Size |
| --- | --- | --- |
| `0` | `resid` | 1 byte |
| `1` | `cmd` | 1 byte |
| `2` | `payload_len` | 1 byte |
| `3..` | payload | `payload_len` bytes |

Transfer limits:

- Device SPI RX/TX transfer buffers are 256 bytes.
- Maximum framed payload is 253 bytes (`256 - 3`).
- The host helper `control_build_spi_data()` returns `3 + payload_len` bytes
  for writes.
- The host helper `control_build_spi_data()` returns 8 bytes for reads: the
  three-byte request header plus five zero padding bytes.

## NOP Transfers

A request with first three bytes all zero is treated as a NOP by the SPI
transport callback:

```text
00 00 00
```

Host code uses follow-up zero-filled transfers to clock out data that the device
prepared after the previous command.

## Default Buffer Behavior

During startup and default-buffer handling, the first TX byte is preset to
`CONTROL_COMMAND_IGNORED_IN_DEVICE` (`7`).

The RPi SPI host code retries while the first returned byte equals
`CONTROL_COMMAND_IGNORED_IN_DEVICE`.

## Write Command Flow

1. Host sends `[resid, cmd(write), payload_len, payload...]`.
2. Device validates the resource and stores the requested command.
3. Device forwards the write payload to the matching servicer.
4. Device prepares a status-only response frame for a follow-up transfer.
5. Host performs a follow-up zero-filled transfer to read the status response.

## Read Command Flow

1. Host sends `[resid, cmd(read), payload_len, padding...]`.
2. Device validates the resource and stores the requested command.
3. Device forwards the read request to the matching handler.
4. Device prepares a payload-available response in the SPI TX buffer.
5. Host performs a follow-up zero-filled transfer to read the payload-available
   response.

Payload-available response frame:

| Byte offset | Field |
| --- | --- |
| `0` | `CONTROL_RET_STATUS_PAYLOAD_AVAIL` (`23`) |
| `1..` | Read payload prepared by the device-control read handler |

The follow-up transfer must clock at least `payload_len + 1` bytes to read the
payload-available marker and the complete read payload.

For servicer read commands, the response payload layout is defined by the
servicer callback. The GPIO read callback uses byte `0` as command status and
byte `1` as returned GPIO data.

## Status-Only Response Frame

When the SPI transport has no read payload to return, it prepares a status-only
frame:

| Byte offset | Field |
| --- | --- |
| `0` | Literal response length marker `1` |
| `1` | `control_ret_t` status returned by `device_control_request()` |
| `2..` | Device status buffer, then zero padding |

The device status buffer has `MAX_STATUS_BUFFER_LEN = 10` bytes. The GPIO
handler can update status-buffer slots with `device_control_set_resource_status()`.

After successful servicer registration, the SPI transport seeds the next TX
buffer with a status-only frame using `CONTROL_SUCCESS`. This gives the host a
valid "device alive" response before any command-specific response is staged.

Current Satellite1 status-buffer layout in status-only frames:

| SPI byte offset | Status-buffer index | Meaning |
| --- | --- | --- |
| `tx[2]` | `0` | Device-control ready flag: `1` means ready |
| `tx[3]` | `1` | `GPIO_CONTROLLER_RESOURCE_IN_A` status |

GPIO `status_register` values are status-buffer indexes, not direct SPI byte
offsets. The SPI byte offset is `2 + status_register`. Because index `0` is now
reserved for the ready flag, GPIO status bytes appear one byte later on the SPI
wire than they did before the ready flag was introduced. Current Satellite1 only
registers and updates `GPIO_CONTROLLER_RESOURCE_IN_A` status.

## Special Resource Commands

`CONTROL_SPECIAL_RESID` (`0`) is reserved by the device-control core.
Application servicers cannot register resource `0`.

Special resource reads return two-byte payloads: byte `0` is command status and
byte `1` is the requested value. On the SPI wire, the payload is returned after
the payload-available marker.

| Command | Encoded value | Direction | Payload length | Response |
| --- | --- | --- | --- | --- |
| `CONTROL_GET_VERSION` | `0x80` | Read | 2 bytes | `[23, CONTROL_SUCCESS, CONTROL_VERSION]` |
| `CONTROL_GET_LAST_COMMAND_STATUS` | `0x81` | Read | 2 bytes | `[23, CONTROL_SUCCESS, last_status]` |

Writes to `CONTROL_SPECIAL_RESID` are rejected with `CONTROL_BAD_COMMAND`.

## Status Codes

`control_ret_t` values are defined in `device_control_shared.h`.

| Name | Value | Meaning |
| --- | --- | --- |
| `CONTROL_SUCCESS` | 0 | Command handled successfully |
| `CONTROL_REGISTRATION_FAILED` | 1 | Servicer registration failed |
| `CONTROL_BAD_COMMAND` | 2 | Unsupported command or invalid command for resource |
| `CONTROL_DATA_LENGTH_ERROR` | 3 | Payload length mismatch |
| `CONTROL_OTHER_TRANSPORT_ERROR` | 4 | Transport-level error |
| `CONTROL_BAD_RESOURCE` | 5 | Resource not registered or invalid for command |
| `CONTROL_MALFORMED_PACKET` | 6 | Packet is too short or malformed |
| `CONTROL_COMMAND_IGNORED_IN_DEVICE` | 7 | Device is not ready or default buffer was used |
| `CONTROL_ERROR` | 8 | Generic error |

`CONTROL_RET_STATUS_PAYLOAD_AVAIL` (`23`) is an SPI transport marker, not a
`control_ret_t` error code. It indicates that bytes `1..` of the same SPI frame
contain a read payload.

Servicer-specific values start at `64`:

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

## Firmware Servicers

This section lists the servicers started by current Satellite1 firmware when
`appconfDEVICE_CTRL_SPI` is enabled.

### GPIO Servicer

References:

- `satellite-xmos-firmware/src/gpio/gpio_servicer.h`
- `satellite-xmos-firmware/src/gpio/gpio_cmds.h`
- `satellite-xmos-firmware/src/gpio/gpio_servicer.c`
- `satellite-xmos-firmware/bsp_config/SATELLITE1/platform/platform_init.c`

Defined resources:

| Resource ID | Symbol | Current Satellite1 registration |
| --- | --- | --- |
| `211` | `GPIO_CONTROLLER_RESOURCE_IN_A` | Registered |
| `212` | `GPIO_CONTROLLER_RESOURCE_IN_B` | Not registered by current Satellite1 board config |
| `221` | `GPIO_CONTROLLER_RESOURCE_OUT_A` | Not registered by current Satellite1 board config |

Defined commands:

| Command | Encoded read value | Encoded write value | Direction | Payload length | Response |
| --- | --- | --- | --- | --- | --- |
| `GPIO_CONTROLLER_SERVICER_CMD_READ_PORT` (`0`) | `0x80` | N/A | Read | 2 bytes | `[23, status, port_value]` |
| `GPIO_CONTROLLER_SERVICER_CMD_WRITE_PORT` (`1`) | N/A | `0x01` | Write | 1 byte | Status-only frame |
| `GPIO_CONTROLLER_SERVICER_CMD_SET_PIN` (`2`) | N/A | `0x02` | Write | 2 bytes: pin, value | Status-only frame |

`GPIO_CONTROLLER_RESOURCE_IN_A` and `GPIO_CONTROLLER_RESOURCE_IN_B` reject write
commands with `CONTROL_BAD_RESOURCE`. `GPIO_CONTROLLER_RESOURCE_OUT_A` supports
write commands when registered by a board config.

### LED Ring Servicer

References:

- `satellite-xmos-firmware/src/led_ring/led_ring_servicer.h`
- `satellite-xmos-firmware/src/led_ring/led_ring_cmds.h`
- `satellite-xmos-firmware/src/led_ring/led_ring_servicer.c`
- `satellite-xmos-firmware/bsp_config/SATELLITE1/platform/driver_instances.h`

Resource:

| Resource ID | Symbol |
| --- | --- |
| `200` | `LED_RING_SERVICER_RESID` |

Command:

| Command | Encoded value | Direction | Payload length | Response |
| --- | --- | --- | --- | --- |
| `LED_RING_SERVICER_CMD_WRITE_RAW` (`0`) | `0x00` | Write | `3 * LED_RING_NUM_LEDS` bytes | Status-only frame |

For Satellite1, `LED_RING_NUM_LEDS` is `24`, so the raw write payload is
`72` bytes. The payload is passed directly to `rtos_ws2812_write()`.

The LED ring servicer does not implement read commands.

### DFU Servicer

References:

- `satellite-xmos-firmware/src/dfu_int/dfu_servicer.h`
- `satellite-xmos-firmware/src/dfu_int/dfu_cmds.h`
- `satellite-xmos-firmware/src/dfu_int/dfu_cmds_map.h`
- `satellite-xmos-firmware/src/dfu_int/dfu_common.c`

Resource:

| Resource ID | Symbol |
| --- | --- |
| `240` | `DFU_CONTROLLER_SERVICER_RESID` |

Commands:

| Command | ID | Direction | Command-map payload length | SPI read request payload length |
| --- | --- | --- | --- | --- |
| `DFU_CONTROLLER_SERVICER_RESID_DFU_DETACH` | `0` | Write | 1 byte | N/A |
| `DFU_CONTROLLER_SERVICER_RESID_DFU_DNLOAD` | `1` | Write | 130 bytes | N/A |
| `DFU_CONTROLLER_SERVICER_RESID_DFU_UPLOAD` | `2` | Read | 130 bytes | 131 bytes |
| `DFU_CONTROLLER_SERVICER_RESID_DFU_GETSTATUS` | `3` | Read | 5 bytes | 6 bytes |
| `DFU_CONTROLLER_SERVICER_RESID_DFU_CLRSTATUS` | `4` | Write | 1 byte | N/A |
| `DFU_CONTROLLER_SERVICER_RESID_DFU_GETSTATE` | `5` | Read | 1 byte | 2 bytes |
| `DFU_CONTROLLER_SERVICER_RESID_DFU_ABORT` | `6` | Write | 1 byte | N/A |
| `DFU_CONTROLLER_SERVICER_RESID_DFU_SETALTERNATE` | `64` | Write | 1 byte | N/A |
| `DFU_CONTROLLER_SERVICER_RESID_DFU_TRANSFERBLOCK` | `65` | Read/write | 2 bytes | 3 bytes when read |
| `DFU_CONTROLLER_SERVICER_RESID_DFU_GETVERSION` | `88` | Read | 5 bytes | 6 bytes |
| `DFU_CONTROLLER_SERVICER_RESID_DFU_REBOOT` | `89` | Write | 1 byte | N/A |
| `DFU_CONTROLLER_SERVICER_RESID_DFU_GETFLASHSERIAL` | `90` | Read | 8 bytes | 9 bytes |
| `DFU_CONTROLLER_SERVICER_RESID_DFU_GETIMAGESTATUS` | `91` | Read | 1 byte | 2 bytes |

Read command encoded values set bit 7. For example,
`DFU_CONTROLLER_SERVICER_RESID_DFU_GETSTATUS` (`3`) is sent as `0x83` for a
read request.

The shared DFU servicer wrapper reserves byte `0` of read payloads for command
status. The SPI read request payload length is therefore one byte larger than
the DFU command-map payload length, and the wire response begins with
`CONTROL_RET_STATUS_PAYLOAD_AVAIL`.

The flash serial command reads the external SPI flash IC unique ID using command
`0x4B` with four dummy bytes. Its successful wire response is
`[23, CONTROL_SUCCESS, serial[0]..serial[7]]`.

The image status command returns one flag byte. Its successful wire response is
`[23, CONTROL_SUCCESS, flags]`.

Image status flags:

| Bit | Mask | Meaning |
| --- | --- | --- |
| `0` | `0x01` | Upgrade image present |
| `1` | `0x02` | Data partition available after the DFU image area |

## Changelog

### `0x11`

- Added explicit SPI read-payload availability framing.
- Read responses now begin with `CONTROL_RET_STATUS_PAYLOAD_AVAIL` (`23`), followed by
  the payload prepared by the device-control read handler.
- Special resource reads now use the same status-plus-data payload convention as
  servicer reads: `[CONTROL_SUCCESS, value]`.
- One-byte read payloads are no longer collapsed into status-only responses.
- SPI seeds an initial status-only response after successful servicer
  registration so hosts can distinguish a live device from no response.
- Satellite1 reports device-control readiness in status-buffer index `0`, which
  moves the GPIO IN_A status byte one byte later on the SPI wire.
- Added additive DFU flash serial read command
  `DFU_CONTROLLER_SERVICER_RESID_DFU_GETFLASHSERIAL` (`90`).
- Added additive DFU image status read command
  `DFU_CONTROLLER_SERVICER_RESID_DFU_GETIMAGESTATUS` (`91`).

### `0x10`

- Previous baseline documented the existing SPI command framing and current
  Satellite1 servicer command set.
- Status-only responses used `tx[0] = 1`, `tx[1] = status`, and `tx[2..]` for
  the device status buffer.
- Servicer read response payloads were defined by individual servicer callbacks.
