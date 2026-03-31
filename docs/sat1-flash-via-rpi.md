# Satellite1 Flash Via Pi CLI

This runbook covers flashing Satellite1 firmware when xTAG is not connected.

## Key point

The Pi-side command writes a raw flash image:

- `sat1 xmos flash-firmware <factory.bin>`

Because this command is partition-unaware, only `.factory.bin` images are valid.

## Prerequisites

- Satellite1 connected to Pi and reachable
- SSH access to Pi host without prompts
- Working Pi-side `sat1` command (or wrapper)

## Environment

Required:

- `SAT1_RPI_HOST=<ssh-host>`

Optional:

- `SAT1_RPI_CLI_CMD=<remote sat1 command>` (default: `sat1`)
- `SAT1_FLASH_SSH_CONNECT_TIMEOUT_S=<seconds>`
- `SAT1_FLASH_REMOTE_SUDO=1` (run remote flash command with `sudo -n`)

## Helper script

Use `tools/e2e/run_sat1_flash_via_rpi.sh`.

Default behavior (`--all`) is:

1. build `satellite1_firmware_fixed_delay.factory.bin`
2. copy image to Pi over SSH/SCP
3. flash with `sat1 xmos flash-firmware`
4. verify with `sat1 xmos read-firmware`

## Commands

Full flow:

```bash
source tools/env/xmos_env.sh
SAT1_RPI_HOST=<ssh-host> tools/e2e/run_sat1_flash_via_rpi.sh --all
```

Build only:

```bash
source tools/env/xmos_env.sh
tools/e2e/run_sat1_flash_via_rpi.sh --build
```

Flash prebuilt image:

```bash
source tools/env/xmos_env.sh
SAT1_RPI_HOST=<ssh-host> tools/e2e/run_sat1_flash_via_rpi.sh --flash --factory-bin build_SATELLITE1/satellite1_firmware_fixed_delay.factory.bin
```

Flash prebuilt image with remote sudo:

```bash
source tools/env/xmos_env.sh
SAT1_RPI_HOST=<ssh-host> SAT1_FLASH_REMOTE_SUDO=1 tools/e2e/run_sat1_flash_via_rpi.sh --flash --factory-bin build_SATELLITE1/satellite1_firmware_fixed_delay.factory.bin
```

Verify only:

```bash
source tools/env/xmos_env.sh
SAT1_RPI_HOST=<ssh-host> tools/e2e/run_sat1_flash_via_rpi.sh --verify
```

Dry-run:

```bash
source tools/env/xmos_env.sh
SAT1_RPI_HOST=<ssh-host> tools/e2e/run_sat1_flash_via_rpi.sh --all --dry-run
```

## flashrom PATH note

On some hosts, `flashrom` is only available under a sudo path (for example
`/usr/sbin/flashrom`) and not in the non-root user PATH. The helper script now
prints remote `flashrom` lookup diagnostics before flashing. If flashing fails
with a `flashrom ... not found` warning, retry with `SAT1_FLASH_REMOTE_SUDO=1`.

## Next step

After successful flash + verify, run Satellite1 HIL tests:

```bash
SAT1_HIL=1 SAT1_RPI_HOST=<ssh-host> .venv/bin/python -m pytest -m "hil and sat1" tests/test_hw_sat1_firmware -q
```
