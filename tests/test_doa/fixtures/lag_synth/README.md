# DoA Lag-Synth WAV Fixtures

Pre-generated deterministic packaged WAV fixtures used by DoA playback tests.

## Why static fixtures

- Avoid per-test waveform generation
- Keep test inputs stable across runs
- Reuse the same artifacts for SAT1 and SQ66 HIL tests

## Included angle fixtures

- `doa_lagsynth_m135.wav`
- `doa_lagsynth_m090.wav`
- `doa_lagsynth_m045.wav`
- `doa_lagsynth_p000.wav`
- `doa_lagsynth_p045.wav`
- `doa_lagsynth_p090.wav`
- `doa_lagsynth_p135.wav`
- `doa_lagsynth_p180.wav`

Each WAV is generated with:

- signal model: `lag-synth`
- single-angle schedule
- segment length: `3 s`
- packed lane format with sync + N/E/S/W + expected angle metadata
