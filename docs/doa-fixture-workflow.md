# DoA Fixture Workflow (Unit + HIL)

This runbook defines one reusable DoA fixture flow that works for both local
algorithm tests and on-device injection checks.

## Why this exists

- Use one generated WAV artifact in two places:
  - local unit validation (`doa_gcc_phat_test --wav ...`)
  - Pi-side HIL evaluation (`run_doa_wav_hil_eval.py`)
- Keep expectations embedded in the WAV itself (lane 5 metadata as `doa_mrad`).

## Signal models

- `lag-synth` (recommended for fixture/regression)
  - deterministic lag-based synthesis
  - designed to match lag/geometry algorithm expectations
  - stable for unit tests
- `pyroom`
  - room/acoustics simulation
  - useful for realistic stimuli, not strict deterministic regression

## Packaged lane layout used by fixture WAVs

- lane 0 (left, phase 0): sync (`0x7E57A55A`)
- lane 1 (left, phase 1): mic N
- lane 2 (left, phase 2): mic E
- lane 3 (right, phase 0): mic S
- lane 4 (right, phase 1): mic W
- lane 5 (right, phase 2): expected angle metadata (`doa_mrad`)

Angle convention in this workflow:

- North = `0` degrees
- clockwise = positive

## Canonical wrapper (recommended)

Use `tools/e2e/run_doa_fixture_hil.sh`.

### 1) Generate + validate fixture locally (no HIL)

```bash
tools/e2e/run_doa_fixture_hil.sh --no-hil
```

This does:

- generate lag-synth WAV + expected JSON + lag CSV in `/tmp`
- build `modules/fph/doa/tests`
- run `doa_gcc_phat_test --wav <generated_wav>`

### 2) Full flow with HIL injection

```bash
SAT1_RPI_HOST=<ssh-host> tools/e2e/run_doa_fixture_hil.sh
```

Common overrides:

```bash
tools/e2e/run_doa_fixture_hil.sh \
  --host <ssh-host> \
  --angles-deg "30,90,150,-90" \
  --segment-s 3 \
  --show-plot \
  --poll-s 0.1 \
  --aplay-dev hw:0,0
```

## Static pytest HIL fixtures (no per-test generation)

HIL playback tests now use pre-generated lag-synth WAV fixtures committed under:

- `tests/test_doa/fixtures/lag_synth`

Fixture selection is angle-based via `tests/test_doa/conftest.py`. If a test angle
does not have a matching fixture WAV, the HIL test is skipped with a message that
lists supported fixture angles.

## Direct script usage (advanced)

Generate fixture WAV directly:

```bash
python3 tools/doa/generate_doa_fixture_set.py \
  --angles-deg "30,90,150,-90" \
  --segment-s 3 \
  --out-wav /tmp/doa_fixture_lagsynth.wav
```

Validate fixture WAV with unit test:

```bash
cmake -S modules/fph/doa/tests -B build_doa_tests
cmake --build build_doa_tests -j
./build_doa_tests/doa_gcc_phat_test --wav /tmp/doa_fixture_lagsynth.wav
```

Run HIL evaluation directly from a prepared WAV:

```bash
python3 tools/e2e/run_doa_wav_hil_eval.py \
  --host <ssh-host> \
  --wav /tmp/doa_fixture_lagsynth.wav \
  --expected-file /tmp/doa_fixture_lagsynth.expected.json \
  --auto-offset \
  --show-plot
```

## Notes

- `doa_gcc_phat_test --wav ...` derives expected per-segment angles from lane 5
  metadata by default.
- Optional legacy override is still available in test binary:
  `--angles-deg ... --segment-s ...`.
