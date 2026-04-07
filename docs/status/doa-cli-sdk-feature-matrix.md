# DoA CLI/SDK Feature Matrix

Date: 2026-03-31

## Purpose

Track current CLI parity for DoA and mic-routing workflows used by HIL tests/tools, and define what is missing vs intentionally deferred.

## Scope reviewed

- `tests/` and `tools/` callsites listed in `docs/status/doa-cli-sdk-gap-status.md`
- Existing observed CLI usage (`sat1 xmos get-doa --mode raw|smooth`)

## Status key

- `Implemented`: CLI command exists and is already used by at least one flow
- `Missing`: CLI command/contract needed for migration is not available
- `Deferred`: intentionally not being implemented now

## Feature matrix

| Area | Capability | SDK callsites today | CLI status | Notes / next action |
|---|---|---|---|---|
| DoA read | Single sample (`raw`, `smooth`) | `tools/doa/plot_live_doa_over_ssh.py`, `tools/e2e/run_doa_wav_hil_eval.py`, `tools/e2e/run_doa_checklist.py`, DoA HIL tests | Implemented | `sat1 xmos get-doa --mode raw|smooth` is in use. Keep as baseline path. |
| DoA read | Streaming samples for low-overhead polling | `tools/doa/plot_live_doa_over_ssh.py`, `tools/e2e/run_doa_wav_hil_eval.py`, `tools/e2e/run_doa_checklist.py` | Missing | Add `sat1 xmos doa stream` (NDJSON, `--period-s`, `--board`, `--count`, deterministic exit semantics). |
| Mic input | Read full mic-input settings | `tests/test_hil/test_mic_input_gain.py`, `tests/test_hw_sq66_firmware/test_sq66_hil_mic_input_gain.py`, `tools/e2e/run_doa_checklist.py`, `tools/doa/plot_live_doa_over_ssh.py`, `tools/e2e/run_doa_wav_hil_eval.py` | Missing | Add `sat1 xmos mic-input get-settings --json`. |
| Mic input | Set mic-input settings (source mode/channel maps/gain) | Same as above + `tests/test_hil/test_audio_input_packaging_and_routing.py` | Missing | Add `sat1 xmos mic-input set-settings --json <payload>`. |
| Mic input | Get available mic count | Mic-input tests/tools above | Missing | Add `sat1 xmos mic-input get-available-mic-count --json`. |
| Mic output | Read full mic-output settings | `tests/test_hil/test_device_control_api.py`, `tests/test_hw_sq66_firmware/test_sq66_hil_mic_output_routing.py` | Missing | Add `sat1 xmos mic-output get-settings --json`. |
| Mic output | Set output channels | Mic-output tests above | Missing | Add `sat1 xmos mic-output set-channels --left <n> --right <n>`. |
| Mic output | Set output packing/upsample map | Mic-output tests above | Missing | Add `sat1 xmos mic-output set-packing --enabled <0|1> --upsample-map <csv>`. |
| DoA debug | Debug stats (`frame_counter`, queue depth, etc.) | `tools/e2e/run_doa_checklist.py` and private/API-gated callsites | Deferred | Keep SDK/private path for now; no CLI parity planned in this phase. |
| DoA debug | Snapshot internals (`_cntrl.transfer` command-level payloads) | DoA SPI tests/tooling that use private transfer internals | Deferred | Keep as temporary exception and remove with later debug-path cleanup. |
| Cross-cutting | Consistent board selection | Mixed callsites across all files above | Missing (partial) | Standardize `--board` behavior across all new commands and streaming command. |

## Decisions locked for this phase

1. DoA debug/snapshot remains on existing SDK/private-transfer path (temporary exception).
2. `sat1 xmos doa stream` is in-scope and should be added as a CLI command.
3. Migration target: remove non-debug direct SDK usage from tests/tools once mic-input/mic-output + stream commands exist.

## Immediate next actions

1. Write CLI command contracts (args, JSON schema, exit/error behavior) for:
   - `sat1 xmos doa stream`
   - all `mic-input` and `mic-output` commands listed above
2. Implement and validate `doa stream` first (unblocks plot/e2e polling paths).
3. Implement mic-input/mic-output parity commands.
4. Migrate non-debug SDK callsites in HIL tests/tools to CLI commands.
5. Keep and document a narrow deferred exception list for debug/snapshot-only callsites.
