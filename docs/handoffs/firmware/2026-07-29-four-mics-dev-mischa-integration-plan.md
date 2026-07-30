# Four-Mics Dev-Mischa Integration Plan

Date: 2026-07-29

## Goal

Create a clean Satellite1-XMOS firmware integration base that combines the production infrastructure work from `dev-mischa` with the relevant four-mic, packaged-audio, audio-control, DoA, and HIL work from `four_mics_sandbox`.

The resulting branch should be suitable for `xmos-audio-pipeline` to consume as its `external/Satellite1-XMOS` submodule before adding deterministic fixed-delay parity hooks.

## Current Inputs

| Checkout | Path | Branch | Commit | State |
|---|---|---:|---:|---|
| Orbit firmware checkout | `/Users/mischa/Projects/FutureProofHomes/orbit/external/Satellite1-XMOS` | `dev-mischa` | `81e080d` | clean |
| Four-mic standalone checkout | `/Users/mischa/Projects/FutureProofHomes/Satellite1-XMOS-15.3-fourmics-port` | `four_mics_sandbox` | `142f5ca` | dirty |
| Pipeline submodule | `/Users/mischa/Projects/FutureProofHomes/xmos-audio-pipeline/external/Satellite1-XMOS` | `develop` | `86cf1ee` | clean, stale for this work |

Remote branch references:

- `origin/develop`: `86cf1ee65be535a972e2ac350756328a1dcd7248`
- `origin/four_mics_sandbox`: `142f5cad74b10295b1946c6f25fb521de73380ca`
- `dev-mischa`: local branch only at time of writing

Observed branch relationship:

- `dev-mischa` and `origin/four_mics_sandbox` diverge from merge base `a2fe0aff72ee2bf57a944ea9bd2cd16e0b544cbe`.
- `dev-mischa` contains production firmware infrastructure work that is not all present on `four_mics_sandbox`.
- `four_mics_sandbox` contains the four-mic/audio-control work required for parity planning.

## Non-Goals

- Do not add deterministic parity SPI resources in this cleanup phase.
- Do not point `xmos-audio-pipeline` at a dirty local firmware checkout.
- Do not wholesale import untracked artifacts, `.env`, WAV scratch files, or local debug outputs.
- Do not rewrite or force-push shared branches unless explicitly approved.
- Do not discard dirty standalone checkout changes before classifying them.

## Integration Strategy

Use `dev-mischa` as the integration base because it is clean and already contains production-facing infrastructure changes.

Create a new integration branch from `dev-mischa`, then bring over the relevant `four_mics_sandbox` work in reviewable groups. Keep the existing branches intact until validation passes.

Suggested branch name:

```bash
dev-mischa-fourmics-integration
```

## Preflight Checklist

Run from `/Users/mischa/Projects/FutureProofHomes/orbit/external/Satellite1-XMOS`:

```bash
git status --short --branch
git rev-parse HEAD
git rev-parse origin/four_mics_sandbox
git merge-base HEAD origin/four_mics_sandbox
git log --left-right --cherry-pick --oneline HEAD...origin/four_mics_sandbox
git submodule status
```

Expected starting state:

- Current branch is `dev-mischa`.
- Worktree is clean.
- `HEAD` is `81e080d` unless new commits were intentionally added.
- `origin/four_mics_sandbox` is reachable.

If the worktree is dirty, stop and classify the local changes before continuing.

## Step 1: Create Integration Branch

Run from the Orbit firmware checkout:

```bash
git switch dev-mischa
git switch -c dev-mischa-fourmics-integration
```

Do not change `dev-mischa` directly.

## Step 2: Build A Focused Diff Inventory

Generate focused inventories before merging:

```bash
git diff --stat HEAD..origin/four_mics_sandbox -- satellite-xmos-firmware modules/fph modules/rtos/modules/sw_services/device_control tools/ci xmos_macros.cmake
git diff --name-status HEAD..origin/four_mics_sandbox -- satellite-xmos-firmware modules/fph modules/rtos/modules/sw_services/device_control tools/ci xmos_macros.cmake
git log --left-right --cherry-pick --oneline HEAD...origin/four_mics_sandbox
```

Keep the generated inventory in the terminal/session notes unless a permanent migration report is desired.

## Step 3: Integrate Four-Mic Firmware Shape

Bring over the structural firmware pieces required for four-mic Satellite1 operation.

Primary files/directories:

- `satellite-xmos-firmware/src/app_conf.h`
- `satellite-xmos-firmware/satellite1.cmake`
- `satellite-xmos-firmware/firmware.cmake`
- `satellite-xmos-firmware/bsp_config/SATELLITE1/`
- `satellite-xmos-firmware/audio_pipelines/reference/fixed_delay/`
- `satellite-xmos-firmware/audio_pipelines/reference/empty/`
- `satellite-xmos-firmware/audio_pipelines/speaker/`

Required outcomes:

- `appconfMIC_PIPELINE_INPUT_CHANNELS` supports `MIC_ARRAY_CONFIG_MIC_COUNT`.
- Fixed-delay `frame_data_t` supports four mic passthrough channels while preserving two AEC ref channels and two proc channels.
- Fixed-delay tile 0 uses `appconfAUDIO_PIPELINE_SKIP_IC_AND_VNR`, not the stale `VAD` spelling.
- `satellite1_firmware_fixed_delay` remains the production target of interest.
- USB audio remains disabled for production Satellite1 unless explicitly re-enabled for another target.

Conflict risks:

- `dev-mischa` removed/changed some USB/device-control paths.
- `four_mics_sandbox` removed older pipeline variants and added SQ66 BSP work.
- Avoid accidentally regressing `dev-mischa` DFU/QSPI/versioning changes in this step.

## Step 4: Integrate Audio Pipeline Control Resources

Bring over the audio pipeline control servicer and runtime settings.

Primary files/directories:

- `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_cmds.h`
- `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_servicer.c`
- `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_servicer.h`
- `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_settings.c`
- `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_settings.h`
- `satellite-xmos-firmware/src/control/audio_cfg_servicer.c`
- `satellite-xmos-firmware/src/control/audio_cfg_servicer.h`
- `satellite-xmos-firmware/src/control/device_control_servicer_config.h`
- `satellite-xmos-firmware/src/main.c`

Required outcomes:

- Resource `230`: mic output settings.
- Resource `231`: speaker settings.
- Resource `232`: mic input settings.
- `APP_DEVICE_CTRL_TOTAL_SERVICER_COUNT` accounts for all enabled servicers.
- The deprecated `audio_cfg_servicer` compatibility shim remains intentional or is explicitly removed with documentation.
- `device_control_ready_task` still reports readiness without racing resource registration.

Conflict risks:

- `dev-mischa` has SPI readiness/status behavior that must not be lost.
- `four_mics_sandbox` may bring back or alter host-side USB device-control pieces that `dev-mischa` removed.

## Step 5: Integrate Packaged Input And Output Routing

Bring over packaged audio routing from `four_mics_sandbox` while preserving `dev-mischa` production constraints.

Primary file:

- `satellite-xmos-firmware/src/main.c`

Required outcomes:
- Packaged ref input mode works through `AUDIO_PIPELINE_REF_SOURCE_PACKAGED_INPUT`.
- Packaged mic input mode works through `AUDIO_PIPELINE_MIC_SOURCE_PACKAGED_INPUT`.
- Sync word remains `0x7E57A55A`.
- Runtime snapshots are available through the mic input settings resource.
- Output channel maps support the intended two-channel I2S output and optional packed extra channels.
- Reference and mic frame queues use fixed pools, not unbounded allocation on the audio path.

Approved follow-up from dirty standalone checkout:

- Include virtual output sync channel `255` in the packaged-output integration.
- Include the Q24 gain conversion in a dedicated gain ABI commit.

## Step 6: Integrate Audio Runtime Gain Support

Bring over runtime input gain support.

Primary files:

- `satellite-xmos-firmware/src/audio_runtime/audio_runtime_gain.c`
- `satellite-xmos-firmware/src/audio_runtime/audio_runtime_gain.h`
- `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_settings.c`
- `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_settings.h`
- `satellite-xmos-firmware/src/main.c`

Required outcomes:

- Ref and mic gains can be controlled through the mic input settings resource.
- Gain fixed-point format is Q24 and explicitly documented in code/docs.
- Unity gain value matches the implementation.

Resolved decision:

- `origin/four_mics_sandbox` appears to use Q30 unity in its committed state.
- The dirty standalone checkout changes this to Q24 unity.
- The final integration should use Q24 because it supports higher absolute runtime gains.
- Q24 is not currently present in `dev-mischa`; it exists only in the dirty standalone checkout.
- Importing the committed `four_mics_sandbox` gain path may temporarily introduce Q30, but the integration must switch to Q24 in a dedicated commit before the branch is considered complete.
- Q24 wire ABI uses unity `0x01000000` and a right shift of 24 after multiply.
- Q30 wire ABI uses unity `0x40000000` and a right shift of 30 after multiply; it only supports just under 2x positive gain in signed `int32_t`, while Q24 supports much larger practical gain values.

## Step 7: Reconcile FPH Device-Control Module Changes

Compare and reconcile `modules/fph/rtos_device_control` carefully.

Primary files/directories:

- `modules/fph/rtos_device_control/CMakeLists.txt`
- `modules/fph/rtos_device_control/api/device_control_shared.h`
- `modules/fph/rtos_device_control/src/device_control.c`
- `modules/fph/rtos_device_control/transport/spi/device_control_spi.c`
- `modules/fph/rtos_device_control/host/`

Required outcomes:

- Preserve `dev-mischa` SPI device-control read-response fixes unless superseded.
- Preserve status-buffer readiness behavior if still used by `main.c`.
- Avoid reintroducing USB host dependency unless explicitly needed.
- If `CONTROL_VERSION` changes, update protocol docs and host tooling expectations.

Resolved decision:

- `four_mics_sandbox` appears to add or retain USB host support and libusb headers.
- `dev-mischa` explicitly removed USB device-control host support.
- Preserve `dev-mischa` SPI-only behavior in this integration.
- Do not reintroduce USB host device-control support from `four_mics_sandbox` in this pass.

## Step 8: Reconcile DFU And QSPI Work

Preserve `dev-mischa` production support unless intentionally replaced.

Primary files/directories:

- `modules/fph/qspi_flash_ext/`
- `satellite-xmos-firmware/src/dfu_int/`
- `satellite-xmos-firmware/bsp_config/SATELLITE1/platform/`
- `satellite-xmos-firmware/src/main.c`

Required outcomes:

- DFU flash serial read remains available if required by production workflows.
- DFU image status read remains available if required by production workflows.
- QSPI flash extension remains available if still used by DFU or image status logic.
- Satellite1 platform init/start changes remain consistent with production SPI and flash behavior.

Conflict risks:

- `four_mics_sandbox` may not include the latest DFU/QSPI changes from `dev-mischa`.
- Keep DFU protocol documentation aligned if command IDs or payloads differ.

## Step 9: Reconcile Versioning And Dev Metadata

Compare `versioning.py`, `firmware_version.txt`, and versioning tests.

Primary files:

- `satellite-xmos-firmware/versioning.py`
- `firmware_version.txt`
- `docs/versioning.md`
- `tests/test_versioning/`
- `tools/ci/firmwares.txt`

Required outcomes:

- Preserve `dev-mischa` dev-build import metadata behavior if still needed.
- Preserve simplified dirty-policy behavior from `dev-mischa` unless intentionally superseded.
- Ensure generated `version.h` behavior works in the intended build directory.

## Step 10: Classify Dirty Standalone Checkout Changes

After `origin/four_mics_sandbox` is integrated, inspect the dirty standalone checkout at `/Users/mischa/Projects/FutureProofHomes/Satellite1-XMOS-15.3-fourmics-port`.

Tracked changes approved for this integration:

- `satellite-xmos-firmware/src/audio_runtime/audio_runtime_gain.*`: Q30 to Q24 conversion.
- `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_settings.*`: virtual sync output channel support.
- `satellite-xmos-firmware/src/main.c`: virtual sync output.
- `satellite-xmos-firmware/bsp_config/SATELLITE1/SATELLITE1.cmake`: mic mapping change.

Tracked changes explicitly out of scope for this integration pass:

- `modules/fph/doa/*`: DoA algorithm/debug changes, unless a minimal compile dependency is required.
- `modules/rtos/modules/sw_services/device_control/*`: dirty nested SPI/device-control changes.

Tracked changes requiring separate decision:

- `.opencode/agents/*` changes.
- `tools/read_firmware_version.py` if it should become a maintained utility.
- `docs/mic-gain-debug-session.md` if it should be a permanent handoff.

Never commit without explicit approval:

- `.env`
- `artifacts/`
- `pattern_fail.wav`
- generated logs or ad-hoc capture outputs

Nested submodule warning:

- The standalone checkout has dirty `modules/rtos` changes.
- These changes are out of scope for this integration pass.
- If they are needed later, commit them in the appropriate nested module or document why they remain local.
- Do not update the parent submodule pointer to a dirty nested checkout.

## Step 11: Documentation Updates

Update documentation only for behavior that is actually integrated.

Likely docs:

- `docs/device-control-spi-protocol.md`
- `docs/device-control-protocol-changelog.md` if present after integration.
- `docs/device-control-command-index.md` if present after integration.
- `docs/handoffs/rpi-sdk/*` if host SDK changes are required.

Required documentation points:

- Resource IDs `230`, `231`, `232` and payload layouts.
- Gain fixed-point format.
- Packaged input lane mapping and sync word.
- Mic/ref input source mode semantics.
- Output channel mapping and any virtual sync channel semantics.
- `CONTROL_VERSION` if changed.

## Step 12: Validation Gates

Run quick static checks first:

```bash
git status --short --branch
git diff --check
```

Run available Python/unit checks as appropriate for the branch:

```bash
python -m pytest tests/test_versioning
python -m pytest tests/test_hil/test_audio_input_packaging_and_routing.py tests/test_hil/test_audio_output_packaging_and_routing.py
```

Run firmware build using the project toolchain environment:

```bash
source tools/env/xmos_env.sh
cmake -B build --toolchain xmos_cmake_toolchain/xs3a.cmake -DBOARD=SATELLITE1
cmake --build build --target create_flash_img_satellite1_firmware_fixed_delay
```

If `tools/env/xmos_env.sh` is unavailable in the integration branch at that point, use the repository's documented XMOS environment setup instead and update this plan.

Optional device/HIL validation after build succeeds:

```bash
python -m pytest tests/test_hil_sat1
```

Only run hardware tests when target devices and required environment variables are explicitly available.

## Step 13: Finalize Integration Branch

Before pushing or using as a submodule target:

```bash
git status --short --branch
git log --oneline --decorate --max-count=20
git diff origin/four_mics_sandbox..HEAD --stat
git diff dev-mischa..HEAD --stat
git submodule status
```

Checklist:

- Worktree is clean.
- No `.env`, artifacts, scratch WAVs, or generated logs are tracked.
- Nested submodules are clean and pinned to intended commits.
- Firmware build passes.
- Relevant protocol docs are updated.
- Branch name and commit hash are recorded in the handoff.

## Step 14: Point `xmos-audio-pipeline` At The Clean Firmware Commit

After the integration branch is validated and pushed, update `/Users/mischa/Projects/FutureProofHomes/xmos-audio-pipeline`.

Recommended steps:

```bash
cd /Users/mischa/Projects/FutureProofHomes/xmos-audio-pipeline/external/Satellite1-XMOS
git fetch origin
git switch dev-mischa-fourmics-integration
git pull --ff-only
```

Then from `/Users/mischa/Projects/FutureProofHomes/xmos-audio-pipeline`:

```bash
git status --short --branch
git diff --submodule
```

Optionally set the submodule branch in `.gitmodules`:

```bash
git config --file .gitmodules submodule.external/Satellite1-XMOS.branch dev-mischa-fourmics-integration
```

Only commit the submodule pointer update after confirming the firmware commit is the intended integration point.

## Rollback Plan

If integration becomes too noisy:

- Keep `dev-mischa` unchanged.
- Delete or abandon only the integration branch.
- Recreate a narrower integration branch and cherry-pick fewer commit groups.

If the `xmos-audio-pipeline` submodule pointer is updated incorrectly:

- Reset only the submodule checkout to the previous commit.
- Restore the superproject submodule pointer before committing.
- Do not use destructive reset commands without explicitly confirming there are no unrelated user changes.

## Resolved Decisions

- Keep `dev-mischa-fourmics-integration` as a pure integration branch.
- Merge manually; do not perform a wholesale merge from `origin/four_mics_sandbox`.
- Preserve `dev-mischa` SPI-only device-control behavior.
- Preserve `dev-mischa` DFU/QSPI behavior.
- Preserve `dev-mischa` versioning behavior for now; revisit separately only if needed.
- Use Q24 as the final audio input gain wire ABI.
- If Q30 gain code is imported from committed `origin/four_mics_sandbox`, switch it to Q24 in a dedicated commit.
- Include virtual sync output channel `255`.
- Include the Satellite1 mic mapping change `1,5,0,4`, but keep it in a dedicated commit.
- Do not include DoA yet unless a minimal firmware dependency is required to compile the Satellite1 path.
- Do not include SQ66 in this integration pass; address SQ66 after the Satellite1 variant is complete.
- Do not include `.opencode` changes yet.
- Do not include dirty standalone `modules/rtos` changes yet.

## Planned Commit Boundaries

1. Add or update the integration planning document.
2. Add Satellite1 audio pipeline control plumbing.
3. Wire Satellite1 packaged audio routing and virtual sync output channel support.
4. Switch audio input gain control to Q24 if the imported source introduced Q30.
5. Update Satellite1 microphone mapping to `1,5,0,4`.
6. Run build/test validation and apply only required compile-fix commits.

Commit boundary details:

- The planning commit should contain only this document.
- The audio-control plumbing commit should avoid DFU/QSPI/versioning/device-control transport changes except where strictly required by build wiring.
- The packaged-routing commit may touch `main.c`, fixed-delay frame shape, and audio pipeline settings validation.
- The Q24 commit should contain only gain ABI changes: unity value, multiply shift, function names, parameter names, docs, and tests/host expectations if present.
- The mic-mapping commit should contain only the `SATELLITE1.cmake` mapping change unless a directly related comment/doc line is needed.
- Do not bundle SQ66, DoA tooling, OpenCode files, artifacts, dirty nested submodules, or generated run outputs into these commits.

## Recommended Next Action

Commit this planning document on `dev-mischa-fourmics-integration`, then perform a narrow first integration pass for the audio-control and fixed-delay four-mic firmware files only. Validate that build configuration still reaches `satellite1_firmware_fixed_delay` before adding DoA/HIL/tooling changes.

## Preflight Results

Preflight was run on 2026-07-29 from `/Users/mischa/Projects/FutureProofHomes/orbit/external/Satellite1-XMOS`.

Created integration branch:

```bash
dev-mischa-fourmics-integration
```

Observed state after branch creation:

- `HEAD`: `81e080df3a455693fc3c18e3fdd10324b4707538`
- `origin/four_mics_sandbox`: `142f5cad74b10295b1946c6f25fb521de73380ca`
- merge base: `a2fe0aff72ee2bf57a944ea9bd2cd16e0b544cbe`
- worktree change: this planning document under `docs/handoffs/firmware/`

Focused firmware diff from `dev-mischa-fourmics-integration` to `origin/four_mics_sandbox`:

```text
168 files changed, 9824 insertions(+), 4520 deletions(-)
```

Key files that require reconciliation rather than blind checkout:

```text
modules/fph/qspi_flash_ext/*
modules/fph/rtos_device_control/*
satellite-xmos-firmware/audio_pipelines/reference/fixed_delay/*
satellite-xmos-firmware/src/audio_pipeline_control/*
satellite-xmos-firmware/src/audio_runtime/*
satellite-xmos-firmware/src/control/device_control_servicer_config.h
satellite-xmos-firmware/src/dfu_int/*
satellite-xmos-firmware/src/main.c
satellite-xmos-firmware/versioning.py
```

Dry-run merge conflict inventory from `git merge-tree HEAD origin/four_mics_sandbox`:

```text
CONFLICT (add/add): docs/device-control-spi-protocol.md
CONFLICT (content): modules/fph/CMakeLists.txt
CONFLICT (content): modules/fph/rtos_device_control/transport/spi/device_control_spi.c
CONFLICT (content): satellite-xmos-firmware/bsp_config/SATELLITE1/platform/platform_init.c
CONFLICT (content): satellite-xmos-firmware/bsp_config/SATELLITE1/platform/platform_start.c
CONFLICT (content): satellite-xmos-firmware/firmware.cmake
CONFLICT (modify/delete): satellite-xmos-firmware/satellite1-usb.cmake
CONFLICT (content): satellite-xmos-firmware/satellite1.cmake
CONFLICT (content): satellite-xmos-firmware/src/main.c
CONFLICT (content): satellite-xmos-firmware/versioning.py
```

Implication:

- A wholesale merge is not the first safe step.
- The first safe implementation pass should be a narrow manual import of `src/audio_pipeline_control`, `src/audio_runtime`, fixed-delay four-mic shape changes, and the minimal `main.c` hooks needed to compile those pieces.
- Device-control SPI, platform start/init, DFU/QSPI, USB target deletion, and versioning are known conflict areas.
- Resolved policy is to preserve `dev-mischa` SPI-only behavior, DFU/QSPI behavior, and versioning behavior unless a later dedicated change explicitly revisits them.
