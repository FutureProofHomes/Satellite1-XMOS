---
name: sat1-hil-e2e-tests
description: Run and triage Satellite1 hardware-in-the-loop tests against Pi-side sat1 CLI integration.
compatibility: opencode
metadata:
  scope: sat1-hil
  workflow: hardware-test
---

## Purpose

Use this skill when validating Satellite1 behavior with real hardware.

This workflow covers:
- Pi-side CLI smoke checks (`sat1 xmos ...` / `sat1 dac ...`)
- mic input gain and output routing tests in `tests/test_hw_sat1_firmware`
- optional flash-first flow via Pi-side CLI when xTAG is unavailable

For test suite layout and local pytest usage, see `docs/sat1-test-suite.md`.

## Primary Entry Point

**Always use the helper script:** `tools/e2e/run_sat1_hil_e2e.sh`

This script handles all environment setup, variable exports, and pytest invocation.
Do not manually run pytest for SAT1 HIL tests unless you have a specific reason.

## Usage

### Full suite (default)
```bash
tools/e2e/run_sat1_hil_e2e.sh --full
```

### Smoke tests only
```bash
tools/e2e/run_sat1_hil_e2e.sh --smoke
```

### Allow skipped tests (exploratory runs)
```bash
tools/e2e/run_sat1_hil_e2e.sh --full --allow-skips
```

### Run specific test(s) via pytest args
```bash
tools/e2e/run_sat1_hil_e2e.sh --full -- -k "mic_gain and sat1"
```

### Override RPi host or CLI commands
```bash
tools/e2e/run_sat1_hil_e2e.sh --full --rpi-host my-pi.local
```

## Script Behavior

The helper script automatically:

1. Sources `tools/env/xmos_env.sh` (loads `.env` with `SAT1_RPI_HOST`, etc.)
2. Exports required env vars: `SAT1_HIL=1`, `SAT1_RPI_HOST`, `SAT1_RPI_CLI_CMD`, `SAT1_RPI_PY_CMD`
3. Enables optional playback/consistency gates by default (e.g., `SAT1_HIL_DOA_PLAYBACK=1`)
4. Runs pytest with fail-fast (`-x`) and no-skip enforcement
5. Reports skipped tests as failures unless `--allow-skips` is used

## Script Options

| Option | Description |
|--------|-------------|
| `--full` | Run full SAT1 HIL suite (default) |
| `--smoke` | Run only smoke test file |
| `--allow-skips` | Don't fail when tests are skipped |
| `--no-fail-fast` | Disable pytest `-x` |
| `--disable-optional` | Don't auto-enable optional playback/consistency gates |
| `--rpi-host HOST` | Override `SAT1_RPI_HOST` |
| `--sat1-cmd CMD` | Override `SAT1_RPI_CLI_CMD` |
| `--sat1-py-cmd CMD` | Override `SAT1_RPI_PY_CMD` |
| `--dry-run` | Print commands without executing |
| `-- <pytest args>` | Pass extra args to pytest (e.g., `-k`, `--maxfail`) |

## Notes

- Satellite1 HIL tests do not depend on xscope logs.
- The script requires `SAT1_RPI_HOST` via `.env` or `--rpi-host` argument.
- For exploratory runs with partial hardware, use `--allow-skips`.
- Full SAT1 HIL runs can exceed 2 minutes; increase the runner/CLI timeout when invoking the suite.
