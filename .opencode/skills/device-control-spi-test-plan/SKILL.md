---
name: device-control-spi-test-plan
description: Build a practical test plan for SPI device-control behavior and servicer correctness, including protocol, status, and error paths.
compatibility: opencode
metadata:
  scope: device-control-testing
  workflow: verification
---

## Purpose

Use this skill to define and execute a focused validation plan for SPI device
control and new/modified servicers.

## Test layers

Cover these layers explicitly:
- protocol framing/transport behavior
- resource routing and callback dispatch
- per-servicer command handling
- hardware integration (if available)

## Required test matrix

At minimum validate:
- valid write command returns expected status
- valid read command returns expected status + payload
- unknown resource returns `CONTROL_BAD_RESOURCE` or equivalent path behavior
- invalid command ID returns servicer command-id error
- payload length mismatch returns length-related error
- malformed packet (`rx_len < 3`) path
- NOP transaction behavior (`00 00 00`)
- `CONTROL_SPECIAL_RESID` version query behavior
- device-ready/status-register behavior (where implemented)

## Repo entrypoints

Hardware-oriented tests live in:
- `tests/test_hil_sat1/`

Current baseline references:
- `tests/test_hil_sat1/conftest.py`
- `tests/test_hil_sat1/test_usb_dfu.py`

When adding SPI tests, prefer creating:
- `tests/test_hil_sat1/test_spi_device_control_*.py`

## Execution guidance

- Use focused pytest node IDs for quick iteration.
- Gate hardware tests behind existing `HW_TESTS` behavior.
- If hardware is unavailable, still produce executable test stubs and a manual
  verification sequence.

## Reporting format

Report results with:
- test case name
- expected behavior
- observed behavior
- pass/fail
- follow-up action for failures

## Non-goals

- Do not broaden into unrelated USB/I2C control testing unless requested.
- Do not silently skip error-path coverage.
