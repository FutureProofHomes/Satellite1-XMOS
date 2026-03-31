# DoA Unit Tests

This unit test validates `doa4_estimate_from_lags()` against synthetic lag inputs.

It also includes a lag-estimation replica check that builds synthetic 4-mic pulse
signals, estimates lags with bounded cross-correlation (`±DOA4_MAX_LAG_SAMPLES`),
and verifies both:
- recovered lag triplet matches expected `(lag10, lag20, lag30)`
- resulting DoA angle still matches expected within tolerance

An additional GCC-PHAT path test validates `doa4_process_frame()` end-to-end
from synthetic 4-mic frame data.

## Test files

- `modules/fph/doa/tests/src/test_doa_from_lags.c`
  - focuses on lag->angle solver behavior
  - supports optional fixture CSV input
- `modules/fph/doa/tests/src/test_doa_gcc_phat.c`
  - exercises GCC-PHAT lag extraction + geometry solve via `doa4_process_frame()`
  - includes channel-order mismatch guard case

## Angle convention

- Input/expected angles in this test use compass convention:
  - North = `0` degrees
  - clockwise = positive
- Internally, the test converts to/from math convention as needed.

## Run the test

From repository root:

```bash
cmake -S modules/fph/doa/tests -B build_doa_tests
cmake --build build_doa_tests -j
ctest --test-dir build_doa_tests --output-on-failure
```

Or run test binaries directly:

```bash
./build_doa_tests/doa_from_lags_test
./build_doa_tests/doa_gcc_phat_test
```

## Tolerances and pass criteria

These thresholds are currently fixed in test code:

- `doa_from_lags_test`
  - angular tolerance: `15` degrees (`tol_deg = 15.0f`)
  - applies to:
    - direct lag->angle cases (`run_angle_case`)
    - fixture CSV cases (`run_fixture_file`)
    - lag-estimation replica path (`run_lag_estimation_replica_case`)
  - channel-order guard: fails if mismatch error is **less than** `20` degrees

- `doa_gcc_phat_test`
  - angular tolerance: `20` degrees (`tol_deg = 20.0f`)
  - applies to end-to-end `doa4_process_frame()` cases (`run_process_case`)
  - applies to WAV-input mode segment mean error checks
  - channel-order guard: fails if mismatch error is **less than** `20` degrees

Why these values are different:

- `doa_from_lags_test` checks mostly deterministic lag->geometry math and can use a tighter tolerance.
- `doa_gcc_phat_test` includes FFT + PHAT + correlation peak picking, so a slightly looser tolerance is used for stable host-side regression checks.
- Channel-order guard uses `20` degrees as a sanity threshold to ensure swapped channels are detectably wrong, not accidentally close.

## Built-in synthetic values

- Built-in expected angles are defined in:
  - `modules/fph/doa/tests/src/test_doa_from_lags.c` (`cases[]` in `main`)
- Built-in synthetic lags are generated in:
  - `modules/fph/doa/tests/src/test_doa_from_lags.c` (`synthesize_lags_from_angle`)

## External fixture mode

`doa_from_lags_test` also accepts an optional fixture CSV:

```bash
./build_doa_tests/doa_from_lags_test /path/to/doa_from_lags_fixture.csv
```

Fixture format:

```text
# angle_deg,lag10,lag20,lag30
0.000000,2,0,-2
45.000000,0,-3,-3
...
```

## Generate fixture CSV with pyroom helper script

From repository root:

```bash
python3 tools/doa/generate_doa_fixture_set.py \
  --angles-deg "0,45,90,135,180,-45,-90,-135" \
  --out-lag-fixture /tmp/doa_from_lags_fixture.csv \
  --fixture-only
```

Then run the test against that fixture:

```bash
./build_doa_tests/doa_from_lags_test /tmp/doa_from_lags_fixture.csv
```

## Run GCC-PHAT test on packed WAV from pyroom generator

`doa_gcc_phat_test` supports a WAV-input mode:

```bash
./build_doa_tests/doa_gcc_phat_test \
  --wav /tmp/doa_pyroom_set.wav
```

For a deterministic fixture WAV that is intended to pass this unit test,
generate the WAV with lag-synth model:

```bash
python3 tools/doa/generate_doa_fixture_set.py \
  --angles-deg "30,90,150,-90" \
  --segment-s 3.0 \
  --out-wav /tmp/doa_fixture_lagsynth.wav

./build_doa_tests/doa_gcc_phat_test --wav /tmp/doa_fixture_lagsynth.wav
```

Optional legacy schedule override is still supported:

```bash
./build_doa_tests/doa_gcc_phat_test \
  --wav /tmp/doa_pyroom_set.wav \
  --angles-deg "30,90,150,-90" \
  --segment-s 3
```

Notes for WAV mode:

- Expected WAV format is PCM `S32_LE`, stereo, `48 kHz`.
- Packed lane decoding assumes the generator layout:
  - lane 0 (left phase 0): sync word (`0x7E57A55A`)
  - lane 1 (left phase 1): N
  - lane 2 (left phase 2): E
  - lane 3 (right phase 0): S
  - lane 4 (right phase 1): W
- lane 5 (right phase 2): expected angle metadata (`doa_mrad`)
- The estimator input order in `gcc_phat.c` is `[N,E,S,W]` (project convention).
- By default, expected per-segment angles are derived directly from lane 5
  metadata changes in the WAV.
- Per segment, frames near transitions are skipped (settling margin), and
  segment mean absolute angle error is compared against tolerance.
