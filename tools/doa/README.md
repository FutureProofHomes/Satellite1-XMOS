# DoA Tooling

This directory contains DoA-specific helper tools.

## Scripts

- `generate_doa_fixture_set.py`
  - Generates deterministic packaged DoA WAV fixtures (lag-synth).
  - Encodes expected angle metadata (`doa_mrad`) into packaged lane 5.

- `plot_live_doa_over_ssh.py`
  - Live DoA plot from remote SPI reads over SSH.

## Conventions

- Compass angle convention for test expectations:
  - North = `0` degrees
  - clockwise = positive
- Packaged lanes:
  - lane 0: sync word
  - lane 1..4: N,E,S,W
  - lane 5: expected angle metadata (`doa_mrad`)

## E2E wrappers

End-to-end orchestration remains in `tools/e2e/`, notably:

- `tools/e2e/run_doa_fixture_hil.sh`
- `tools/e2e/run_doa_wav_hil_eval.py`

Pyroomacoustics simulation utilities live under `simulations/doa_pyroom/`.
