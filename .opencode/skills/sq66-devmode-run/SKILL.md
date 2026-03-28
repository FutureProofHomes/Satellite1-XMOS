---
name: sq66-devmode-run
description: Build, run, and debug the SQ66 dev-mode firmware using the dedicated OpenCode tool, with the repo helper script as fallback.
compatibility: opencode
metadata:
  scope: sq66-bringup
  workflow: tool-first
---

## Purpose

Use this skill for local SQ66 bring-up when you need a known-good dev-mode workflow for:
- adapter detection
- dev-mode firmware build validation
- xscope execution
- debugger launch

Prefer the dedicated `run_sq66_dev` OpenCode tool for this workflow.
Use the repo helper script only if the tool is unavailable or clearly broken.

This skill is the single source of truth for fixed SQ66 bring-up procedure details.
Do not duplicate step-by-step fixed workflow instructions in `AGENTS.md` or subagent files.

## Primary interface

Primary interface:
- `run_sq66_dev`

Fallback implementation:
- `tools/e2e/run_sq66_dev.sh`

## Default assumptions

- load `tools/env/xmos_env.sh` before validating SQ66 env vars in shell checks
- build directory: `build_sq66_dev`
- target: `sq66_firmware_fixed_delay`
- configuration: `-DUSE_DEV_MODE=ON`
- XMOS environment wrapper: `tools/env/xmos_env.sh`
- `.venv` is activated automatically if present
- local Python env helper: `tools/env/python_env.sh --setup --with-tests && source .venv/bin/activate`
- adapter id may be auto-detected if not explicitly provided

## Tool usage

Prefer these tool calls:

- detect adapter only:
  - `run_sq66_dev(detectOnly=true)`
- build only:
  - `run_sq66_dev(mode="build")`
- run with xscope logs:
  - `run_sq66_dev(mode="run")`
- debugger launch:
  - `run_sq66_dev(mode="debug")`

Optional arguments:
- `adapterId`
- `buildDir`
- `target`
- `skipBuild`
- `dryRun`

Examples:
- `run_sq66_dev(mode="run")`
- `run_sq66_dev(mode="debug", adapterId="7A3VAER2")`
- `run_sq66_dev(detectOnly=true)`
- `run_sq66_dev(mode="build", dryRun=true)`

## Fallback script usage

Only use the helper script directly if the `run_sq66_dev` tool is unavailable.

Preferred fallback invocations:
- detect adapter only:
  - `tools/e2e/run_sq66_dev.sh --detect-only`
- build only:
  - `tools/e2e/run_sq66_dev.sh --build`
- run with xscope logs:
  - `tools/e2e/run_sq66_dev.sh --run`
- debugger launch:
  - `tools/e2e/run_sq66_dev.sh --debug`

Avoid reconstructing this workflow manually with ad hoc `cmake`, `xrun`, `xgdb`, environment setup, or adapter-detection commands unless both the tool and helper script are unavailable.

## Execution policy

- Prefer the `run_sq66_dev` tool over bash.
- When manually validating environment variables, source `tools/env/xmos_env.sh` first in the same shell.
- Do not manually set up XMOS environment, `.venv`, adapter detection, build, run, or debug steps when the dedicated tool or helper script can do it.
- Do not use destructive cleanup commands such as `rm -rf build_sq66_dev` unless explicitly required by the task.
- Use `dryRun=true` when the user wants to inspect the exact command path without executing it.
- Use `detectOnly=true` before asking the user for adapter help.
- If operating in a restricted or planning context, do not bypass agent restrictions with ad hoc shell commands.
- Do not inspect external XMOS toolchain doc/version files for this workflow; rely on `tools/env/xmos_env.sh` and the helper script/tool outcomes.

## Failure handling

- no adapter found:
  - check USB/xTAG connection and rerun adapter detection
- multiple adapters found:
  - require explicit `adapterId` unless project policy says otherwise
- build failure:
  - report the failure clearly before attempting run or debug
- xscope run failure:
  - retry with explicit adapter id if detection succeeded but launch failed
- debugger attach failure:
  - check for stale `xgdb` or `xrun` processes still holding the adapter
- missing artifact:
  - confirm build completed successfully and expected target/build directory were used
- tool failure:
  - if `run_sq66_dev` fails due to tool wiring rather than firmware workflow, fall back to the helper script

## Expected dev-mode output

In dev-mode, firmware outputs memory analysis periodically via xscope, for example:

```text
Tile[N]:
    Minimum heap free: X bytes
    Current heap free: Y bytes
