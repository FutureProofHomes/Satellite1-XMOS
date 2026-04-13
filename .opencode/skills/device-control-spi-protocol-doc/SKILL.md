---
name: device-control-spi-protocol-doc
description: Document the SPI device-control protocol from implementation truth, including packet format, read/write flow, and status semantics.
compatibility: opencode
metadata:
  scope: device-control-spi-docs
  workflow: docs-first
---

## Purpose

Use this skill to create or update protocol documentation for SPI device control,
grounded in current firmware and host implementation behavior.

For quick command-inventory Q&A (no doc edits), use `device-control-command-lookup` instead.

## Source of truth

Always derive protocol behavior from:
- `modules/fph/rtos_device_control/transport/spi/device_control_spi.c`
- `modules/fph/rtos_device_control/src/device_control.c`
- `modules/fph/rtos_device_control/host/control_host_support.h`
- `modules/fph/rtos_device_control/host/device_access_spi_rpi.c`
- `modules/fph/rtos_device_control/api/device_control_shared.h`

Do not infer behavior from stale docs when code disagrees.

## Required coverage

Document all of the following:
- SPI request frame: `resid(1) + cmd(1) + payload_len(1) + payload`
- read-bit semantics for commands (`bit7`)
- NOP behavior (`0x00 0x00 0x00`) and why it exists
- default-buffer/drop behavior and `CONTROL_COMMAND_IGNORED_IN_DEVICE`
- malformed packet handling and return statuses
- write command response semantics
- read command response semantics (status byte location and payload layout)
- special resource behavior (`CONTROL_SPECIAL_RESID`, version/status commands)
- status buffer behavior and device-ready signaling
- inventory of firmware servicers reachable through this protocol
- function/purpose of each servicer and each resource it exposes

## Versioning policy

- Bump `CONTROL_VERSION` for any device-control protocol change.
- Add or update a protocol changelog entry for the new version.
- Ensure the protocol doc references the changelog for compatibility checks.

## Servicer inventory requirements

When producing protocol documentation, include a dedicated section that lists all
currently available firmware servicers that use device control over SPI.

At minimum include:
- servicer name
- source file path
- resource ID(s)
- command IDs (or command enum names)
- brief function/purpose
- build or feature gating notes (for example optional servicers)

Use implementation truth from firmware sources, especially:
- `satellite-xmos-firmware/src/main.c`
- `satellite-xmos-firmware/src/control/servicer.h`
- `satellite-xmos-firmware/src/gpio/gpio_servicer.h`
- `satellite-xmos-firmware/src/dfu_int/dfu_servicer.h`
- `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_settings.h`
- `satellite-xmos-firmware/src/led_ring/led_ring_servicer.h`

## Output format

When updating docs, produce:
- a short protocol overview
- a byte-level packet table
- command sequence examples for read and write
- status/return-code table
- a servicer inventory table (name, resources, commands, function)
- known constraints and caveats

Preferred doc location:
- `docs/device-control-spi-protocol.md`

## Consistency checks

Before finalizing docs, verify:
- all status codes are names present in `control_ret_t`
- payload length descriptions match code paths
- examples reflect actual host behavior in SPI host helper code
- no contradiction with existing `modules/rtos/.../device_control_protocol.rst`

## Non-goals

- Do not change servicer logic as part of documentation-only tasks.
- Do not invent host APIs not present in this repo.
