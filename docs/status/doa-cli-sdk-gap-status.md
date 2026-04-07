# DoA CLI vs SDK Status

Date: 2026-03-31

## Scope reviewed

Scanned `tests/` and `tools/` for direct Python SDK usage (`satellite1.sat1_hat.XMOS` and related low-level components) instead of `sat1` CLI.

## Progress since initial gap report

### Completed

1. **Unified mic pipeline CLI landed in Satellite1-RPi and deployed to test Pi**
   - `sat1 xmos get-mic-pipeline-settings --json`
   - `sat1 xmos set-mic-pipeline-settings --json <payload>`

2. **DoA streaming landed in Satellite1-RPi CLI**
   - `sat1 xmos get-doa --stream --period-s <sec> [--count N] [--mode raw|smooth|both]`

3. **Tooling migrations completed in this repo**
   - `tools/e2e/run_doa_wav_hil_eval.py`: migrated from remote SDK snippets to remote CLI commands
   - `tools/doa/plot_live_doa_over_ssh.py`: migrated from remote SDK snippets to remote CLI commands
   - `tools/e2e/run_doa_checklist.py`: migrated from remote SDK snippets to remote CLI commands

4. **CLI path env var strategy migrated**
   - Introduced `SAT1_RPI_CLI_CMD` and `SQ66_RPI_CLI_CMD`
   - Removed `*_RPI_SAT1_CMD` references
   - Updated tests/tools/docs/skills to use `*_RPI_CLI_CMD`
   - `tools/e2e/run_doa_fixture_hil.sh` now accepts/passes `--sat1-cmd`

### Runtime note observed during validation

- We observed a real device/runtime stall case where DoA `seq` stopped advancing and values stayed constant.
- After XMOS reset and re-applying live mic settings, `seq` resumed and values changed again.
- This indicates stream plumbing is working; occasional static output can still originate upstream in firmware/runtime state.

## Files still using direct SDK calls

### Tests (SDK still in use)

- `tests/test_hil_sat1/test_sat1_hil_doa_spi.py`
- `tests/test_hw_sq66_firmware/test_sq66_hil_doa_spi.py`
- `tests/test_hw_sq66_firmware/test_sq66_hil_doa_playback.py`
- `tests/test_hil/test_mic_input_gain.py`
- `tests/test_hw_sq66_firmware/test_sq66_hil_mic_input_gain.py`
- `tests/test_hil/test_device_control_api.py`
- `tests/test_hw_sq66_firmware/test_sq66_hil_mic_output_routing.py`
- `tests/test_hil/test_audio_input_packaging_and_routing.py`
- `tests/test_hil/test_audio_output_packaging_and_routing.py`

### Tools (SDK still in use)

- None in scoped DoA tooling

## Remaining gaps

1. **SDK-to-CLI migration gap in tests**
   - Many HIL tests still call SDK directly for mic input/output settings and some DoA reads.

2. **Deferred by design: debug/snapshot private transfer paths**
   - `_cntrl.transfer` command-level snapshot/debug reads remain out-of-scope for CLI parity in this phase.

## Continue plan (recommended)

1. **Migrate non-debug HIL tests off SDK**
   - Prioritize mic-input gain tests and mic-output routing tests on SAT1 + SQ66.

2. **Keep a narrow deferred exception list**
   - Only snapshot/debug private-transfer callsites remain on SDK until removed.

3. **Stability hardening for long DoA runs**
   - Add a lightweight preflight in DoA tools/tests: verify `seq` advances over a short window before proceeding.

## Related status doc

- See `docs/status/doa-cli-sdk-feature-matrix.md` for capability-level tracking.
