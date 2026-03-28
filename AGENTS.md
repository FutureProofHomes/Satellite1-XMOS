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
  - sq66 hil / e2e tests
  - sq66 full end-to-end run
  - device-control SDK handoff
  - device-control command lookup

## Agent routing
- Use `xmos-board-bringup` for deterministic SQ66 dev-mode build/run/debug execution, including expected-output checks via xscope/xgdb.
- Use `xmos-debug-investigation` for intermittent, unknown, or multi-layer SQ66 failures that require exploratory diagnostics.
- If deterministic bring-up fails or expected output is not observed, hand off from `xmos-board-bringup` to `xmos-debug-investigation`.
- Use `code-review` for analysis-only requests (review findings, risk checks, and read-only validation).
- Use `code-modifier` for implementation requests (fixes, refactors, feature edits, and test updates).
- For SQ66 fixed workflows, always load `sq66-devmode-run` and prefer the `run_sq66_dev` tool.
- For SQ66 HIL/e2e validation, load `sq66-hil-e2e-tests` before running pytest hardware checks.
- For prompts like "build sq66 in dev mode and run full end-to-end test", load `sq66-full-e2e` and follow it exactly.
- Use `SQ66_RPI_SAT1_CMD` to point HIL tests at a non-default Pi-side SDK command; default is plain `sat1`.
- For full SQ66 HIL selections that include remote Python snippets, `SQ66_RPI_SAT1_CMD` must support both CLI calls and `-c` Python execution (wrapper command recommended).
- For any SPI device-control protocol changes intended for SDK consumption, load `device-control-sdk-handoff` and generate/update a handoff file.
- Treat command-level deltas in existing servicers as protocol changes (for example adding/changing command IDs, direction, or payload layout).
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


## Setup Commands
- Initialize the XMOS build environment first: `source tools/env/xmos_env.sh`.
- Copy `.env.example` to `.env` for local machine-specific overrides when needed.
- Create a Python venv: `python3.10 -m venv .venv`.
- Activate it: `source .venv/bin/activate`.
- Install build dependency: `pip install -r requirements.txt`.
- Install test dependency: `pip install -r requirements_tests.txt`.
- Install firmware Python tooling into the active venv when needed: `python -m pip install xmos-ai-tools`.
- CI scripts can also create `build_venv/` automatically via `tools/ci/helper_functions.sh`.

## Primary Build Commands
- Run the XMOS environment setup in the same shell before any command in this section.
- Activate the repo venv in the same shell as well so CMake finds the correct Python packages.
- Configure firmware build: `cmake -B build --toolchain xmos_cmake_toolchain/xs3a.cmake`.
- Build one firmware target: `cmake --build build -j --target satellite1_firmware_fixed_delay`.
- Build the SQ66 firmware target: `cmake --build build_sq66 -j --target sq66_firmware_fixed_delay`.
- Build the SQ66 dev-mode firmware target: `cmake --build build_sq66_dev -j --target sq66_firmware_fixed_delay`.
- Build upgrade image: `cmake --build build -j --target create_upgrade_img_satellite1_firmware_fixed_delay`.
- Build factory image: `cmake --build build -j --target create_flash_img_satellite1_firmware_fixed_delay`.
- Build a data partition when needed: `cmake --build build -j --target make_data_partition_satellite1_firmware_fixed_delay`.
- If you need all FFVA pipeline variants, configure with `-DENABLE_ALL_FFVA_PIPELINES=1`.
- Use `-j` on firmware build invocations to make use of all available CPU cores.
- Known good local sequence: `source tools/env/xmos_env.sh && source .venv/bin/activate && cmake -B build --toolchain xmos_cmake_toolchain/xs3a.cmake && cmake --build build -j --target satellite1_firmware_fixed_delay`.
- Known good SQ66 dev-mode sequence: `source tools/env/xmos_env.sh && source .venv/bin/activate && cmake -B build_sq66_dev --toolchain xmos_cmake_toolchain/xs3a.cmake -DUSE_DEV_MODE=ON && cmake --build build_sq66_dev -j --target sq66_firmware_fixed_delay`.

## Board-Specific Build Pattern
- CI commonly uses board-specific build directories such as `build_SATELLITE1`.
- Equivalent local configure pattern: `cmake -B build_SATELLITE1 -DCMAKE_TOOLCHAIN_FILE=xmos_cmake_toolchain/xs3a.cmake -DBOARD=SATELLITE1 -DENABLE_ALL_FFVA_PIPELINES=1`.
- Host tools are built separately from firmware.
- SQ66 local configure pattern: `cmake -B build_sq66 --toolchain xmos_cmake_toolchain/xs3a.cmake`.
- SQ66 dev-mode configure pattern: `cmake -B build_sq66_dev --toolchain xmos_cmake_toolchain/xs3a.cmake -DUSE_DEV_MODE=ON`.

## SQ66 Run And Debug
- SQ66 firmware artifact path: `build_sq66/sq66_firmware_fixed_delay.xe`.
- SQ66 dev-mode firmware artifact path: `build_sq66_dev/sq66_firmware_fixed_delay.xe`.
- Use `USE_DEV_MODE=ON` for SQ66 bring-up when you need `rtos_printf()` over xscope; it enables debug printing and disables the watchdog.
- Preferred helper workflow: `tools/e2e/run_sq66_dev.sh`.
- For exact run/debug command flows, defaults, and failure handling, use `.opencode/skills/sq66-devmode-run/SKILL.md`.

## Host Build Commands
- Run the XMOS environment setup in the same shell before configuring host tools.
- Configure host tools: `cmake -B build_host`.
- Build host tools: `cmake --build build_host`.
- CI copies tools like `fatfs_mkimage`, `datapartition_mkimage`, `xscope_host_endpoint`, and `nibble_swap` from `build_host/`.
- Local host builds may still fail unless the xscope host dependency resolves `XSCOPE_ENDPOINT_LIB`; verify that dependency before assuming `build_host` is portable.

## CI Entry Points
- Build host apps the same way CI does: `bash tools/ci/build_host_apps.sh`.
- Build firmware artifacts the same way CI does: `bash tools/ci/build_firmware.sh tools/ci/firmwares.txt`.
- CI uses Docker image `ghcr.io/xmos/xcore_builder:v3.1` and writes artifacts into `dist/` and `dist_host/`.

## Test Commands
- Main repo-level tests are pytest tests under `tests/`.
- Run all repo Python tests: `pytest tests`.
- Run one test file: `pytest tests/test_versioning/test_git.py`.
- Run one test function: `pytest tests/test_versioning/test_git.py::test_git_info -q`.
- Run version parsing tests only: `pytest tests/test_versioning/test_version_parsing.py -q`.
- Prefer `-q` for focused runs and `-k <expr>` when narrowing by name.

## Hardware Test Notes
- Hardware-oriented pytest lives in `tests/test_hw_sat1_firmware/`.
- Those tests rely on Orbit helpers like `orbit.builder.xmos` and `orbit.testing.xmos`.
- They also reference a `HW_TESTS` setting imported from `tests.conftest`; verify local hardware-test setup before assuming they can run.
- Firmware-under-test defaults to `satellite1_firmware_fixed_delay` and build dir `build_test_satellite1_firmware_fixed_delay`.
- Expect xTAG/USB device access for these tests.

## Single-Test Guidance
- For pytest, prefer node IDs: `pytest path/to/test_file.py::test_name -q`.
- For parametrized pytest cases, append the full node ID shown by `pytest -q` collection output.
- Some module-local tests are generated/build-driven; inspect the local `CMakeLists.txt` before assuming direct pytest execution works.
- For CTest-based trees, use `ctest --test-dir <build-dir> --output-on-failure`.
- For a single CTest test, use `ctest --test-dir <build-dir> -R "^exact_test_name$" --output-on-failure`.

## Generated and Versioned Outputs
- `satellite-xmos-firmware/src/version.h` is generated by `satellite-xmos-firmware/versioning.py`.
- Do not hand-edit generated version headers.
- The canonical version source is `firmware_version.txt` unless the versioning CLI is invoked with explicit overrides.
- Build targets in `satellite-xmos-firmware/*.cmake` depend on version generation targets.

## Formatting and Linting Reality
- There is no repo-wide top-level lint command checked into the root.
- There is no root `.clang-format`, `.clang-tidy`, `pyproject.toml`, or `.pre-commit-config.yaml`.
- Do not invent a formatter or lint workflow for the whole repo.
- Instead, preserve the style of the file you are editing.
- Some subtrees have local formatting rules; honor them when working there.

## Known Formatter Configs
- `modules/rtos/.clang-format` exists and uses 4-space indentation, 80-column limit, no tabs, pointer alignment right, and `SortIncludes: false`.
- `modules/inferencing/lib_nn/.github/workflows/auto-format.yaml` references Google C/C++ style for that subtree.
- Several vendored inference submodules also contain their own `.clang-format` files.
- If a file lives under a subtree with local formatting config, use that config only for that subtree.

## C/C++ Style Conventions
- Preserve the existing copyright/license banner when present.
- Use 4 spaces for indentation; do not introduce tabs.
- Keep lines reasonably close to 80 columns where practical.
- Prefer existing brace style: function opening braces on the next line in C/C++, control-statement braces inline when already used that way.
- Keep pointer stars adjacent to the type when following local style, e.g. `rtos_gpio_t *ctx`.
- Avoid re-sorting includes unless the local formatter/config explicitly does so.

## Include Ordering
- Follow the common grouping already used in `satellite-xmos-firmware/src/main.c` and related files.
- System/platform headers first.
- RTOS or library headers next.
- App/project headers last.
- Keep related includes grouped with a blank line between major groups.

## Naming Conventions
- Macros are typically uppercase or `appconf...` for configuration toggles.
- Typedef names usually end in `_t`.
- C functions are `snake_case`.
- CMake targets and libraries are lowercase with namespace-style aliases such as `fph::ffva::ap::fixed_delay`.
- Pytest tests use `test_*` names and live in `test_*.py` files.

## Types and Data Handling
- Use fixed-width integer types for firmware-facing data paths, e.g. `uint8_t`, `int32_t`, `uint32_t`.
- Keep buffer sizes and payload sizes explicit; this codebase frequently validates lengths before use.
- In Python, existing code uses type hints sparingly but accepts them where helpful, especially for `Path` and return types.
- Do not replace established C structs/enums/macros with C++ abstractions in C-only areas.

## Error Handling
- Use `xassert()` for invariants that should never fail in firmware code.
- Return existing status/error enums instead of inventing new ad hoc values.
- For command handlers, update payload/status fields consistently before returning, following patterns in `gpio_servicer.c`.
- In Python CLI code, existing patterns use `SystemExit` or `sys.exit(1)` on unrecoverable user-facing errors.
- In tests, use plain `assert` and `pytest.raises(...)` rather than custom wrappers unless the subtree already has one.

## Memory and Concurrency
- Be careful with RTOS queues, intertile transfers, ISR callbacks, and ownership of malloc'd buffers.
- Preserve comments that explain ownership or cross-tile lifetime; they are often documenting non-obvious contracts.
- Do not change blocking semantics (`portMAX_DELAY`, `RTOS_OSAL_WAIT_FOREVER`, etc.) unless the task specifically requires it.

## CMake Conventions
- Prefer target-based CMake edits over global flags when extending existing files.
- Match the local pattern: `target_sources()`, `target_include_directories()`, `target_compile_definitions()`, `target_link_libraries()`, then options.
- Keep library aliases and target names descriptive and consistent with existing firmware naming.
- Avoid unnecessary new globbing patterns; this repo already uses some, but explicit lists are often easier to reason about.

## Python Conventions
- Standard library imports first, third-party next, local imports last.
- Use `Path` over raw string path manipulation when editing Python utilities.
- Preserve the current lightweight CLI style in `versioning.py`; do not introduce heavy frameworks.
- Keep test code simple and explicit; mocking is done with `unittest.mock.patch` in existing tests.

## Comments and Documentation
- Keep comments only where they clarify hardware behavior, ownership, timing, or protocol details.
- Avoid adding obvious comments to straightforward assignments or control flow.
- Update docs when changing versioning, build, or flashing behavior.

## Agent Workflow Recommendations
- Read the nearest `CMakeLists.txt` before editing build logic.
- Check whether a file is generated before editing it.
- Prefer small, local changes in first-party code over sweeping edits across vendored modules.
- When adding tests, provide the exact single-test command in your final notes.
- When build/test coverage is partial because hardware or toolchains are unavailable, state that clearly.
