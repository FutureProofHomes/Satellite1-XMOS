# Device-Control SPI Protocol (Code-Derived)

This document is derived purely from implementation in:

- `modules/fph/rtos_device_control/transport/spi/device_control_spi.c`
- `modules/fph/rtos_device_control/src/device_control.c`
- `modules/fph/rtos_device_control/host/device_access_spi_rpi.c`
- `modules/fph/rtos_device_control/host/control_host_support.h`
- `modules/fph/rtos_device_control/api/device_control_shared.h`

No external docs were used as protocol truth for this file.

## SPI State Machine (Implementation Truth)

| Step | Host TX Pattern | Device Path | Device Response Buffer (`spi_xfer_tx_buf`) | Host-Side Meaning |
| --- | --- | --- | --- | --- |
| 0. Startup / not ready | any transfer before registration complete | default SPI buffer path | `tx[0] = CONTROL_COMMAND_IGNORED_IN_DEVICE (7)` | host should retry |
| 0b. Startup / first status-only | first transfer after registration | SPI start callback prefill | `tx[0]=1`, `tx[1]=CONTROL_SUCCESS`, `tx[2..]=status_buffer` (may still be zeros) | status-only frame indicates device is alive before any response is staged |
| 1. Command frame received | `[resid, cmd, payload_len, ...]` with `rx_len < 3` | malformed-packet branch in SPI callback | status-only frame with `ret=CONTROL_MALFORMED_PACKET` | command rejected |
| 2. NOP fetch frame | header `00 00 00` | NOP branch (no new request) | previously prepared tx buffer remains valid | clocks out prior response |
| 3. Normal request accepted | `rx_len >= 3`, header not `000` | `device_control_request()` then `device_control_payload_transfer_bidir()` | depends on read/write result | command processed |
| 4. Write command execution | write cmd (`bit7=0`) | core validates/calls servicer | `tx_buf[0]=ret`, `num_response_bytes` remains `1` | write result staged |
| 5. Status-only wrap | when `num_response_bytes == 1` (no payload queued for this transfer) | SPI callback wrapper | `tx[0]=1`, `tx[1]=ret`, `tx[2..]=status_buffer` | status-only frame carrying current status buffer |
| 6. Read command execution | read cmd (`bit7=1`) | core calls servicer with `tx_buf` output and sets `tx_size=requested_payload_len` | payload emitted directly from `tx_buf[0..]` | read payload frame |
| 7. Resource missing at request | unknown `resid` in `device_control_request()` | request rejects | status-only frame with `ret=CONTROL_BAD_COMMAND` | request rejected pre-servicer |
| 8. Resource missing at transfer | lookup fail in transfer core | core sets `tx_buf[0]=CONTROL_BAD_RESOURCE` | status-only frame | bad resource error |
| 9. Host read API behavior | read command 2-phase flow | `control_read_command()` copies raw payload | function returns `CONTROL_SUCCESS` unconditionally | caller must inspect payload/status convention |
| 10. Host write API behavior | write command + status fetch | `control_write_command()` | returns first byte of fetched status response | write status returned directly |

## Wire Framing

### Request Header

Always 3 bytes:

- `byte0 = resid`
- `byte1 = cmd`
- `byte2 = payload_len`

From `control_build_spi_data()`.

### Host Request Length

- Read command (`cmd & 0x80`): fixed request frame length `8` bytes.
- Write command: `3 + payload_len`.

## Command Execution Split

### Write commands

In `device_control_payload_transfer_bidir()`:

- Validates RX payload length.
- Calls servicer write handler.
- Stores status in `tx_buf[0]`.
- SPI layer emits status-only wrapper (`tx[0]=1`, `tx[1]=ret`, `tx[2..]=status_buffer`).

### Read commands

In `device_control_payload_transfer_bidir()`:

- Calls servicer read handler with `tx_buf` as destination.
- Sets `*tx_size = requested_payload_len`.
- SPI layer does not inject extra payload-available marker for this path.

## Busy / Not Ready Signaling

The only explicit "not ready / dropped" marker in SPI transport code is:

- `CONTROL_COMMAND_IGNORED_IN_DEVICE` (`7`) in default TX buffer.

Host loops retry while first returned byte equals this value.

## NOP Behavior

`00 00 00` request header is treated as NOP in SPI callback and used to clock out the previously prepared response buffer.

## Special Resource

Reserved resource:

- `CONTROL_SPECIAL_RESID = 0`

Read commands:

- `CONTROL_GET_VERSION` (`0x80`) -> protocol version byte.
- `CONTROL_GET_LAST_COMMAND_STATUS` (`0x81`) -> last command status byte.

## Critical Derived Observation

There is no `RET_PAYLOAD_AVAILABLE` / `0x17` concept in this module’s SPI transport implementation. Any host stack relying on `0x17` as a required read-response marker is not derived from this code path.
