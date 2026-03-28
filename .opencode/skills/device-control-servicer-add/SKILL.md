---
name: device-control-servicer-add
description: Add a new SPI device-control servicer safely, including resource mapping, registration, task startup, and integration checks.
compatibility: opencode
metadata:
  scope: device-control-servicer
  workflow: implementation
---

## Purpose

Use this skill when implementing a new device-control servicer (resource + command
handler) for SPI control.

## Baseline references

Model implementation patterns after:
- `satellite-xmos-firmware/src/gpio/gpio_servicer.c`
- `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_servicer.c`
- `satellite-xmos-firmware/src/led_ring/led_ring_servicer.c`
- `satellite-xmos-firmware/src/dfu_int/dfu_servicer.c`

Core control API references:
- `modules/fph/rtos_device_control/api/device_control.h`
- `modules/fph/rtos_device_control/src/device_control.c`
- `satellite-xmos-firmware/src/control/servicer.h`

## Required implementation steps

1. Define resource ID(s) and command ID(s)
- Add or update a `*_cmds.h` file for command enums.
- Ensure resource IDs do not collide with existing servicers.

2. Define command map
- Add `control_cmd_info_t` map entries with correct direction and payload shape.
- Validate expected payload size (`num_vals * bytes_per_val`).

3. Implement callbacks
- Implement read callback: reserve/update status byte in `payload[0]` as required.
- Implement write callback: validate and apply payload.
- Use `validate_cmd()` and return explicit `control_ret_t` codes.

4. Register and run servicer task
- Register resource list via `device_control_servicer_register()`.
- Run receive loop with `device_control_servicer_cmd_recv()`.

5. Integrate startup path
- Wire task creation in `satellite-xmos-firmware/src/main.c`.
- Ensure tile placement matches platform architecture.

6. Update expected servicer count
- Update host-mode `device_control_init(... servicer_count, ...)` in each active BSP:
  - `satellite-xmos-firmware/bsp_config/SATELLITE1/platform/platform_init.c`
  - `satellite-xmos-firmware/bsp_config/SATELLITE1-USB/platform/platform_init.c`
  - `satellite-xmos-firmware/bsp_config/XCORE-AI-EXPLORER/platform/platform_init.c`
  - `satellite-xmos-firmware/bsp_config/XK-VOICE-SQ66/platform/platform_init.c`

7. Create SDK handoff description
- Use `device-control-sdk-handoff` to create/update:
  - `docs/handoffs/rpi-sdk/YYYY-MM-DD-<short-topic>-handoff.md`
- Include resource/command IDs, payload delta, compatibility notes, and explicit Satellite1-RPi update requirements.

8. Refresh command index
- Update `docs/device-control-command-index.md` when any resource ID, command ID,
  command direction, or payload shape changes.
- Keep the Audio Pipeline section aligned with:
  - `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_cmds.h`
  - `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_settings.h`
  - `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_servicer.c`

## Review checklist

- Resource IDs are unique and documented.
- Command read/write bit semantics are correct.
- Read payload reserves byte 0 for status where required.
- Payload lengths and command-map entries agree.
- Servicer registration count matches configured servicers.
- Off-tile/on-tile routing assumptions are valid.

## Non-goals

- Do not modify vendored code under `modules/` unless required.
- Do not change transport protocol framing while adding a servicer.
