# Satellite1 Test Suite

This document describes the SAT1 (Satellite1) test coverage in this repo and how
to run it locally.

## Scope and layout

SAT1-related tests live under `tests/` and fall into two main groups:

- `tests/test_hil/`: shared HIL tests (SAT1 + SQ66) that exercise device-control
  APIs and audio routing via the Pi-side CLI. These are gated behind `SAT1_HIL=1`.
- `tests/test_hil_sat1/`: SAT1-only HIL tests (DAC, smoke, DOA, flash checks).
- `tests/test_doa/`: DOA fixtures and checks that support SAT1 behavior (some
  are pure Python, others may rely on captured data).

Non-SAT1 tests (for example, versioning checks or SQ66 HIL) also live in
`tests/`, but are outside the scope of this doc.

## Prerequisites for SAT1 HIL

HIL tests require a reachable Pi and a deployed SAT1 CLI:

- `SAT1_HIL=1` enables the SAT1 HIL test suite.
- `SAT1_RPI_HOST` must point at the Pi (e.g. `pi@<ip>`). The fixture skips if
  it is not set.
- `SAT1_RPI_CLI_CMD` optionally overrides the CLI on the Pi. Default is `sat1`.
- `SAT1_RPI_PY_CMD` optionally overrides the Python interpreter on the Pi for
  helper scripts. Default is `/opt/satellite1/venv/bin/python`.

Audio I/O defaults to ALSA device `hw:0,0` for playback and `hw:0,1` for record.
Override with:

- `SAT1_HIL_APLAY_DEV` (default `hw:0,0`)
- `SAT1_HIL_ARECORD_DEV` (default `hw:0,1`)

## Running SAT1 tests

Run the full SAT1 HIL suite:

```bash
SAT1_HIL=1 SAT1_RPI_HOST=pi@<ip> pytest tests/test_hil tests/test_hil_sat1 -q
```

Run a single test file:

```bash
SAT1_HIL=1 SAT1_RPI_HOST=pi@<ip> pytest tests/test_hil/test_device_control_api.py -q
```

Run a single test case:

```bash
SAT1_HIL=1 SAT1_RPI_HOST=pi@<ip> pytest tests/test_hil/test_device_control_api.py::test_hil_device_control_mic_output_get_settings_shape -q
```

## Markers and gating

Shared HIL tests are tagged with `@pytest.mark.hil` and are guarded by the
`require_hil` fixture. SAT1-only tests in `tests/test_hil_sat1/` also use
`@pytest.mark.sat1` for board-specific selection. If `SAT1_HIL` is not enabled,
SAT1 board cases are skipped.

## Common SAT1 HIL test coverage

Key areas covered in `tests/test_hil/` and `tests/test_hil_sat1/`:

- Mic input gain behavior and signal integrity.
- Mic input/output packaging and routing behavior.
- Device-control API coverage for mic input/output settings.
- DOA SPI interactions and playback verification.
- Basic smoke checks for firmware readiness.

## Related docs

- `docs/sat1-manual-hil-e2e.md` for manual bring-up steps and E2E workflow.
- `docs/doa-fixture-workflow.md` for DOA fixture setup details.
