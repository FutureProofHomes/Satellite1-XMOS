---
name: sat1-flash-via-rpi
description: Build a Satellite1 factory image and flash it from the Pi-side sat1 CLI when xTAG is unavailable.
compatibility: opencode
metadata:
  scope: sat1-flash
  workflow: hardware-flash
---

## Purpose

Use this skill when Satellite1 firmware must be flashed without an xTAG adapter.

This workflow covers:
- local factory image build (`*.factory.bin`)
- upload to Pi host
- Pi-side flash via `sat1 xmos flash-firmware`
- firmware readback verification

## Primary interface

Use:
- `tools/e2e/run_sat1_flash_via_rpi.sh`

## Required environment

Source XMOS env before running the flow:

- `source tools/env/xmos_env.sh`

Set these before flash/verify steps:

- `SAT1_RPI_HOST=<ssh-host>`

Optional:

- `SAT1_RPI_SAT1_CMD=<remote sat1 command>` (default: `sat1`)
- `SAT1_FLASH_SSH_CONNECT_TIMEOUT_S=<seconds>`
- `SAT1_FLASH_REMOTE_SUDO=1` (run remote flash command under `sudo -n`)

## Important constraints

- Pi-side command used by this workflow:
  - `sat1 xmos flash-firmware <factory.bin>`
- Only `.factory.bin` images are valid for this path.
- `.upgrade.bin` is intentionally not supported in this skill.

## Commands

Full flow (build + flash + verify):

- `source tools/env/xmos_env.sh && SAT1_RPI_HOST=<ssh-host> tools/e2e/run_sat1_flash_via_rpi.sh --all`

Build only:

- `source tools/env/xmos_env.sh && tools/e2e/run_sat1_flash_via_rpi.sh --build`

Flash only (prebuilt image):

- `source tools/env/xmos_env.sh && SAT1_RPI_HOST=<ssh-host> tools/e2e/run_sat1_flash_via_rpi.sh --flash --factory-bin build_SATELLITE1/satellite1_firmware_fixed_delay.factory.bin`

Flash only with remote sudo:

- `source tools/env/xmos_env.sh && SAT1_RPI_HOST=<ssh-host> SAT1_FLASH_REMOTE_SUDO=1 tools/e2e/run_sat1_flash_via_rpi.sh --flash --factory-bin build_SATELLITE1/satellite1_firmware_fixed_delay.factory.bin`

Verify only:

- `source tools/env/xmos_env.sh && SAT1_RPI_HOST=<ssh-host> tools/e2e/run_sat1_flash_via_rpi.sh --verify`

Dry run:

- `source tools/env/xmos_env.sh && SAT1_RPI_HOST=<ssh-host> tools/e2e/run_sat1_flash_via_rpi.sh --all --dry-run`

## Recommended execution order

1. Preflight Pi-side command:
   - `ssh "$SAT1_RPI_HOST" "${SAT1_RPI_SAT1_CMD:-sat1} --help"`
2. Build factory image (`--build`) or run full flow (`--all`).
3. Flash via Pi-side CLI (`--flash` or as part of `--all`).
4. Verify firmware readback (`--verify` or as part of `--all`).
5. Run Sat1 HIL tests after a successful flash.

## Failure triage

- SSH/connectivity failure:
  - validate `SAT1_RPI_HOST`, keys, and reachability
- `sat1` command not found on Pi:
  - set `SAT1_RPI_SAT1_CMD` to the deployed command path/wrapper
- flash logs `flashrom ... not found on PATH`:
  - run with `SAT1_FLASH_REMOTE_SUDO=1` (or `--remote-sudo`)
  - verify host has non-interactive sudo for the flashing command
- flash command rejects image:
  - confirm file ends with `.factory.bin`
- missing local artifact:
  - rerun `--build` and confirm `<target>.factory.bin` exists
- verify output empty:
  - rerun `sat1 xmos read-firmware` directly on Pi to inspect runtime state
