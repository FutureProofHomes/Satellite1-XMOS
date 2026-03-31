# DoA Pyroom Simulation

This directory contains pyroomacoustics-based DoA simulation/validation tools.

## TL;DR

```bash
# 1) Generate pyroom WAV
python3 simulations/doa_pyroom/generate_pyroom_doa_set.py \
  --signal-model pyroom \
  --angles-deg "30,90,150,-90" \
  --segment-s 3 \
  --seed 123 \
  --source-distance-m 2.0 \
  --noise-std 0.05 \
  --fmax-hz 3200 \
  --out-wav /tmp/doa_pyroom_set.wav \
  --out-expected /tmp/doa_pyroom_set.expected.json

# 2) Run software-only GCC-PHAT evaluation + JSON report
python3 simulations/doa_pyroom/run_doa_gcc_eval.py \
  --wav /tmp/doa_pyroom_set.wav \
  --out-json /tmp/doa_pyroom_eval.json
```

## What this is for

- Generate realistic (room + noise) packaged DoA WAVs.
- Run simulation-level checks of geometry/channel-order/convention assumptions.
- Probe how the current GCC-PHAT + geometry implementation behaves on pyroom data.

## Generate pyroom samples

From repo root:

```bash
python3 simulations/doa_pyroom/generate_pyroom_doa_set.py \
  --signal-model pyroom \
  --angles-deg "30,90,150,-90" \
  --segment-s 3 \
  --seed 123 \
  --source-distance-m 2.0 \
  --noise-std 0.05 \
  --fmax-hz 3200 \
  --out-wav /tmp/doa_pyroom_set.wav \
  --out-expected /tmp/doa_pyroom_set.expected.json
```

Useful outputs:

- WAV packed for firmware injection (`S32_LE`, stereo, 48k)
- expected schedule JSON
- lane 5 metadata with expected angle (`doa_mrad`)

Useful pyroom tuning switches:

- `--noise-std <float>`: set source noise amount (`0` disables added noise).
- `--source-distance-m <float>`: set source distance from array center.
- `--fmax-hz <float>`: set chirp upper frequency (try `<=2200` to reduce aliasing risk with 71 mm baseline).
- `--source-type <chirp|noise|sine|multitone>`: choose source excitation type.
- `--tone-hz <float>`: tone frequency for `--source-type sine`.
- `--multitone-hz <csv>`: frequencies for `--source-type multitone`.

## Run simulation tests (no hardware)

```bash
pytest simulations/doa_pyroom/test_pyroom_unit.py -q
```

Important scope of `test_pyroom_unit.py`:

- It validates consistency of the pyroom simulation setup:
  - geometry assumptions,
  - angle convention behavior,
  - channel-order sensitivity.
- It does **not** validate firmware transport/injection flow.
- It is not the canonical firmware-functional regression gate.

## Check current firmware algorithm behavior on pyroom WAV (host-side)

Use the helper runner to build and execute `doa_gcc_phat_test` and store a
reproducibility JSON report:

```bash
python3 simulations/doa_pyroom/run_doa_gcc_eval.py \
  --wav /tmp/doa_pyroom_set.wav \
  --out-json /tmp/doa_pyroom_eval.json
```

The JSON report contains:

- input WAV path, size, SHA256,
- adjacent expected schedule JSON (if present),
- exact configure/build/run commands,
- tool stdout/stderr,
- return codes,
- git revision and platform metadata.
- per-segment results (`expected_deg`, `mean_est_deg`, `mean_err_deg`, `frames`).

Runtime behavior of `run_doa_gcc_eval.py`:

- Prints a summary table at the end of each run.
- Returns non-zero only for structural failures (configure/build/run/file/format issues).
- If estimates are out of tolerance but execution is structurally valid, it reports
  `estimates_out_of_range` in JSON and exits `0` (with warning).

If you need manual expected schedule override while running WAV mode:

```bash
python3 simulations/doa_pyroom/run_doa_gcc_eval.py \
  --wav /tmp/doa_pyroom_set.wav \
  --angles-deg "30,90,150,-90" \
  --segment-s 3 \
  --out-json /tmp/doa_pyroom_eval_override.json
```

## GCC-PHAT signal dependencies (important)

GCC-PHAT behavior is strongly dependent on source signal characteristics.

- Broadband excitation generally works best (sharper, less ambiguous delay peaks).
- Narrowband/periodic excitation (pure sine, sparse tones) is often ambiguous and
  can produce unstable or biased lag peaks.
- PHAT weighting improves reverberation robustness but can over-weight low-SNR bins.
- With this array aperture (71 mm max baseline), higher-frequency content is more
  sensitive to phase ambiguity/aliasing effects.

Observed in this repo's pyroom sweeps:

- White-noise source (`--source-type noise`) performed best in software-only eval.
- Chirp/multitone/pure-sine often showed much larger segment mean errors.
- This is expected behavior for GCC-PHAT, not necessarily a structural failure.

Recommended characterization profile:

```bash
python3 simulations/doa_pyroom/generate_pyroom_doa_set.py \
  --signal-model pyroom \
  --source-type noise \
  --angles-deg "30,90,150,-90" \
  --segment-s 2 \
  --source-distance-m 1.0 \
  --noise-std 0 \
  --out-wav /tmp/doa_pyroom_noise.wav \
  --out-expected /tmp/doa_pyroom_noise.expected.json

python3 simulations/doa_pyroom/run_doa_gcc_eval.py \
  --wav /tmp/doa_pyroom_noise.wav \
  --out-json /tmp/doa_pyroom_noise_eval.json
```

Background references:

- C. Knapp and G. Carter, "The Generalized Correlation Method for Estimation of Time Delay", 1976.
- M. Brandstein and D. Ward (eds.), "Microphone Arrays", 2001.
- J. Benesty, J. Chen, and Y. Huang, "Microphone Array Signal Processing", 2008.

Note: pyroom data is realistic and may not satisfy strict deterministic tolerance.
Treat this as behavior characterization, not a hard pass/fail firmware gate.

## Structure recommendation

- Use `run_doa_gcc_eval.py` as the default software-only workflow.
- Keep pyroom simulation and characterization in this folder.
- Keep firmware functional gates under `tests/` and HIL tooling under `tools/e2e`.
- If we later need richer per-frame/per-segment C metrics, add a dedicated app in
  `modules/fph/doa`; for now the wrapper keeps the workflow reproducible and simple.

## Run similar check on hardware

Use the generic HIL evaluator script directly:

```bash
python3 tools/e2e/run_doa_wav_hil_eval.py \
  --host "$SAT1_RPI_HOST" \
  --wav /tmp/doa_pyroom_set.wav \
  --expected-file /tmp/doa_pyroom_set.expected.json \
  --auto-offset \
  --out-json /tmp/doa_pyroom_hil_eval.json
```

Optional GUI overlay while evaluating:

```bash
python3 tools/e2e/run_doa_wav_hil_eval.py \
  --host "$SAT1_RPI_HOST" \
  --wav /tmp/doa_pyroom_set.wav \
  --expected-file /tmp/doa_pyroom_set.expected.json \
  --auto-offset \
  --show-plot \
  --out-json /tmp/doa_pyroom_hil_eval_plot.json
```

This script handles upload, packaged-input routing, playback, DoA collection,
segment summary, JSON report generation, and restoration of original settings.

## Optional: manual build/run without wrapper

Use this only if you need direct control over the C test invocation.

```bash
cmake -S modules/fph/doa/tests -B build_doa_tests
cmake --build build_doa_tests -j
./build_doa_tests/doa_gcc_phat_test --wav /tmp/doa_pyroom_set.wav
```
