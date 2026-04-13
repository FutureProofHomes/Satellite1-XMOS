# AGENTS.md

## OpenCode execution rules

Use native OpenCode tools by default.
Do not substitute bash for native tools.

- Read files with read/search/glob tools.
- Edit files with edit or patch.
- Create files with write.
- Use bash only for tests, builds, package manager commands, git, and project CLIs.
- Never use bash heredocs or redirection to create or edit files when native file tools exist.
- Never claim a command was run unless the tool was actually called.
- In plan mode, do not try to bypass restrictions with bash.
- If bash is needed, use the smallest possible command.
- If bash validation fails, retry with a short `description` field.
- In plan mode, you are not allowed to call bash, tell the user to switch to build mode

### Preferred skills

When a relevant skill exists, use the `skill` tool to load it before proceeding.
Check for matching skills for:
  - sq66 devmode run / test
  - sat1 xTAG dev run / debug
  - sq66 hil / e2e tests
  - sq66 full end-to-end run
  - sat1 hil / e2e tests
  - sat1 flash via rpi cli
  - device-control SPI protocol docs
  - device-control SDK handoff
  - device-control command lookup

## Agent routing
- Use `firmware-builder` for firmware build/configuration and artifact generation.
- Use `firmware-runner` for flashing and run/debug workflows via repo scripts.
- Use `xmos-debug-investigation` for intermittent, unknown, or multi-layer SQ66 failures that require exploratory diagnostics.
- Use `code-reviewer` for review/cleanup tasks and for any edit that requires style or convention guidance.
- Use `firmware-coder` for firmware changes in C/XC/asm.
- Use `project-maintainer` for tests, CMake/build system changes, and tooling/scripts.
- Use `test-runner` for managing and running tests, especially HIL or CI-like workflows with clear triage output.
- Use `device-control-owner` for device-control protocol or command inventory changes, including SPI transport behavior and servicer command definitions.
- For SQ66 fixed workflows, always load `sq66-devmode-run` and prefer the `run_sq66_dev` tool.
- For SQ66 HIL/e2e validation, load `sq66-hil-e2e-tests` before running pytest hardware checks.
- For prompts like "build sq66 in dev mode and run full end-to-end test", load `sq66-full-e2e` and follow it exactly.
- For Satellite1 HIL/e2e validation, load `sat1-hil-e2e-tests` before running pytest hardware checks.
- For Satellite1 flash without xTAG, load `sat1-flash-via-rpi` and use `tools/e2e/run_sat1_flash_via_rpi.sh`.
- For Satellite1 xTAG bring-up/run/debug without xscope, load `sat1-dev-xtag-run` and use `tools/e2e/run_sat1_dev_xtag.sh`.
- Use `SQ66_RPI_CLI_CMD` to point HIL tests at a non-default Pi-side SDK command; default is plain `sat1`.
- For full SQ66 HIL selections that include remote Python snippets, `SQ66_RPI_CLI_CMD` must support both CLI calls and `-c` Python execution (wrapper command recommended).
- For any SPI device-control protocol changes intended for SDK consumption, load `device-control-sdk-handoff` and generate/update a handoff file.
- Treat command-level deltas in existing servicers as protocol changes (for example adding/changing command IDs, direction, or payload layout).
- For any device-control protocol or command change, bump `CONTROL_VERSION` and add/update a protocol changelog entry.
- For command-inventory questions (for example "list audio pipeline device-control commands"), load `device-control-command-lookup` and use targeted file reads instead of broad codebase scans.
- For fast command lookup, prefer `docs/device-control-command-index.md` before deeper source inspection.
- Keep SQ66 fixed workflow procedure details in `.opencode/skills/sq66-devmode-run/SKILL.md` as the single source of truth.

### SQ66 execution guardrail

- Do not manually probe external XMOS toolchain files (for example `XMOS_XTC_15.3.1/doc/version.txt`) when running SQ66 workflows.
- Use only the repo wrappers and scripts (`tools/env/xmos_env.sh`, `tools/e2e/run_sq66_dev.sh`) and pytest commands defined in skills.
- SDK deploy/install on target Pi is out of scope for XMOS HIL skills; require a working Pi-side command instead.

## Scope
- This file gives repository-specific guidance for coding agents working in `Satellite1-XMOS-15.3`.
- Follow these notes before falling back to generic C/C++/Python advice.
- The repo is primarily XMOS firmware plus host utilities, Python helpers, and pytest-based checks.
- Large parts of `modules/` are vendored XMOS or third-party code; change them only when the task truly requires it.

## Rules Files
- No Cursor rules were found in `.cursor/rules/`.
- No `.cursorrules` file was found.
- No Copilot instructions file was found at `.github/copilot-instructions.md`.
- Treat this `AGENTS.md` as the top-level agent guidance unless a deeper directory adds its own instructions later.

## Repo Layout
- Top-level firmware build entrypoint: `CMakeLists.txt`.
- Main firmware sources: `satellite-xmos-firmware/`.
- First-party support modules: `modules/fph/`.
- Python tests for this repo: `tests/`.
- CI helper scripts: `tools/ci/`.
- Version generation logic: `satellite-xmos-firmware/versioning.py`.
- Release/version notes: `docs/versioning.md`.

## Environment Expectations
- Before any firmware or host build that depends on XMOS tools, run `source tools/env/xmos_env.sh` in the current shell.
- `tools/env/xmos_env.sh` is the repo-local entrypoint for XMOS environment setup; it sources a root `.env` file when present, uses `XMOS_XTC_ROOT` when set, and otherwise falls back to the default local install path.
- XMOS XTC tools 15.3.x are expected; the repo/toolchain naming is built around `xs3a`.
- Python 3.10 is the documented baseline in `requirements.txt`.
- Submodules matter; clone with `--recursive` or run `git submodule update --init --recursive`.
- The build forbids in-source CMake configuration.

## SQ66 firmware workflow

For SQ66 dev-mode bring-up, load `sq66-devmode-run` first and use the `run_sq66_dev` tool.

Do not duplicate fixed SQ66 runbook details in this file; keep those in the skill.

## Build and Test Entry Points
- Environment setup: `tools/env/xmos_env.sh` (XMOS) and `tools/env/python_env.sh` (Python venv setup).
- CI build scripts: `tools/ci/build_host_apps.sh` and `tools/ci/build_firmware.sh`.
- CMake entrypoints: configure with `xmos_cmake_toolchain/xs3a.cmake` into board-specific `build*` directories.
- SQ66 dev-mode: use `sq66-devmode-run` + `run_sq66_dev` and `tools/e2e/run_sq66_dev.sh`.
- Satellite1 xTAG bring-up: use `sat1-dev-xtag-run` and `tools/e2e/run_sat1_dev_xtag.sh`.
- Satellite1 flash via RPi: use `sat1-flash-via-rpi` and `tools/e2e/run_sat1_flash_via_rpi.sh`.
- HIL tests: use `sq66-hil-e2e-tests` or `sat1-hil-e2e-tests`.

## Test Notes
- Repo tests live under `tests/`; prefer pytest node IDs for focused runs.
- Hardware tests under `tests/test_hil_sat1/` require xTAG/USB access and `HW_TESTS` setup in `tests.conftest`.

## Generated and Versioned Outputs
- `satellite-xmos-firmware/src/version.h` is generated by `satellite-xmos-firmware/versioning.py`.
- Do not hand-edit generated version headers.
- The canonical version source is `firmware_version.txt` unless the versioning CLI is invoked with explicit overrides.
- Build targets in `satellite-xmos-firmware/*.cmake` depend on version generation targets.
