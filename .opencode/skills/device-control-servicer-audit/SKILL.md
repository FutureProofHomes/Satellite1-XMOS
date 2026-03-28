---
name: device-control-servicer-audit
description: Audit SPI device-control and servicer changes for integration risks before merge.
compatibility: opencode
metadata:
  scope: device-control-review
  workflow: analysis
---

## Purpose

Use this skill for analysis-only review of device-control and servicer changes,
with emphasis on regression and integration risk.

## Audit focus

1. Resource ownership and collisions
- Verify each resource ID is unique across GPIO/DFU/audio/LED/new servicers.

2. Command-map correctness
- Confirm command IDs, direction, and payload sizes are internally consistent.

3. Status-byte semantics
- Confirm read/write paths set and return statuses consistently.
- Confirm reserved status byte handling for read payloads.

4. Transport/protocol alignment
- Verify servicer assumptions match SPI transport behavior and host framing.

5. Registration and startup
- Verify servicer registration count matches actual started servicers.
- Verify startup order does not race resource registration.

6. Tile/intertile behavior
- Verify on-tile vs off-tile behavior for callbacks and payload buffers.

## Files to inspect first

- `modules/fph/rtos_device_control/src/device_control.c`
- `modules/fph/rtos_device_control/transport/spi/device_control_spi.c`
- `satellite-xmos-firmware/src/main.c`
- `satellite-xmos-firmware/src/control/servicer.c`
- `satellite-xmos-firmware/src/gpio/gpio_servicer.c`
- `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_servicer.c`
- `satellite-xmos-firmware/src/led_ring/led_ring_servicer.c`
- `satellite-xmos-firmware/src/dfu_int/dfu_servicer.c`
- `satellite-xmos-firmware/bsp_config/*/platform/platform_init.c`

## Output expectations

Return findings as:
- severity (`high`, `medium`, `low`)
- file path
- concise issue description
- why it matters
- concrete remediation

If no issues are found, explicitly state checks performed.

## Non-goals

- Do not apply code changes during audit-only requests.
