# Implementation Plan: Host-Based DSP Audio Test Harness

## Goal

Build a host-compiled test harness that runs the Satellite1 XMOS audio DSP
pipeline (AEC + IC + VNR + NS + AGC) on x86, feeds it synthetic stimuli, and
produces a 3-layer pass/fail/regression signal for CI on every PR.

**No hardware required. No XMOS toolchain. No ESP32.**

---

## 1. Key Finding: Reuse Existing fwk_voice Example

The `fwk_voice` submodule (`modules/voice`) already contains a complete,
x86-compatible pipeline example:

```
modules/voice/examples/bare-metal/pipeline_single_threaded/
├── CMakeLists.txt          # Builds for both XCORE and x86
├── src/
│   ├── pipeline.c          # AEC→IC→VNR→NS→AGC frame processing
│   ├── pipeline_config.h   # 2 mic, 2 ref, 240-sample frames, 10+5 phases
│   ├── pipeline_state.h    # State structs
│   ├── test_wav.c          # WAV I/O + x86 main() at line 155
│   └── main.xc            # XCORE entry (not used for x86)
```

**Why this works for us:**

| Property | Detail |
|----------|--------|
| x86 build | `CMakeLists.txt:29` adds `-DX86_BUILD=1`; `test_wav.c:155` has `int main()` |
| Config match | `pipeline_config.h`: `AP_MAX_Y_CHANNELS=2`, `AP_MAX_X_CHANNELS=2`, `AP_FRAME_ADVANCE=240`, `AEC_MAIN_FILTER_PHASES=10`, `AEC_SHADOW_FILTER_PHASES=5` — identical to Satellite1 |
| AEC | Calls `aec_process_frame_1thread()` via `stage_1_process_frame()` (same function as firmware) |
| IC + VNR | `ic_filter()`, `ic_calc_vnr_pred()`, `ic_adapt()` — same as `audio_pipeline_t0.c` |
| NS | `ns_process_frame()` per channel |
| AGC | `agc_process_frame()` with `AGC_PROFILE_ASR` |
| ADEC | Bypassed (`adec_conf.bypass=1`, `force_de_cycle_trigger=0`) — no effect on output |
| Delay buffer | Initialized at 0 samples — passthrough, same as firmware `appconfINPUT_SAMPLES_MIC_DELAY_MS=0` |
| I/O | 4-channel 32-bit WAV in, 2-channel 32-bit WAV out (POSIX `open()`/`lseek()`) |
| Linking | Static on Linux (`-static`), self-contained binary |

**The only difference from firmware:** the firmware applies 10x mic gain
(`mic_gain_10x()` in `main.c:39`) before the pipeline. Our stimuli will be
post-gain (i.e., at the level the pipeline actually receives on-device).

---

## 2. Build Dependencies

| Dependency | Source | Purpose |
|------------|--------|---------|
| `lib_xcore_math` v2.4.0 | CMake `FetchContent` from `github.com/xmos/lib_xcore_math` | BFP math (FFT, complex ops) |
| `xmos-ai-tools` 1.3.1 | `pip install xmos-ai-tools==1.3.1` | TFLite Micro static lib + `xcore-opt` model converter |
| `trained_model.tflite` | In repo: `modules/voice/modules/lib_vnr/python/model/model_output/trained_model.tflite` | VNR inference model (13 KB) |
| CMake >= 3.21 | System package (`sudo apt install cmake`) | Build system |
| GCC/G++ >= 9 | System package (`sudo apt install gcc g++`) | Compiler (C11 + C++11 for TFLite) |
| NumPy, SciPy | `pip install numpy scipy` | Stimulus generation, metrics |
| pytest | `pip install pytest` | Test runner |

**Build command:**

```bash
git submodule update --init modules/voice
pip install xmos-ai-tools==1.3.1 numpy scipy pytest

cmake -B build-host -S modules/voice -DCMAKE_BUILD_TYPE=Release
cmake --build build-host --target fwk_voice_example_bare_metal_pipeline_single_thread -j$(nproc)
```

**First build** fetches `lib_xcore_math` (~10 s) and compiles ~20 C files +
TFLite model conversion (~30-60 s). Subsequent builds are incremental (< 10 s).

**Note:** The VNR inference library (`lib_vnr`) is pulled in transitively by
`lib_ic` (`CMakeLists.txt:26-27`). The `xmos-ai-tools` package provides the
host-side `tflite_micro` static library and the `xcore-opt` command that
converts the `.tflite` model to C++ at build time.

---

## 3. Test Harness Architecture

```
tests/test_dsp_host/
├── CMakeLists.txt              # Builds fwk_voice pipeline example for x86
├── conftest.py                 # Pytest fixtures (binary path, run pipeline)
├── test_dsp_gates.py           # Layer 1: Binary gates (pass/fail)
├── test_dsp_regression.py      # Layer 2: Regression delta vs. baselines
├── test_dsp_informational.py   # Layer 3: Informational metrics (reported only)
├── metrics.py                  # Audio metric functions
├── generate_stimuli.py         # Script to generate all 12 test stimuli
├── stimuli/                    # 12 WAV files (4ch, 32-bit, 16 kHz) — committed
│   ├── speech_clean.wav
│   ├── speech_echo.wav
│   ├── speech_babble.wav
│   ├── speech_quiet.wav
│   ├── speech_loud.wav
│   ├── silence.wav
│   ├── noise_only.wav
│   ├── tone_sweep.wav
│   ├── impulse.wav
│   ├── barge_in.wav
│   ├── wake_word.wav
│   └── commands.wav
├── baselines/                  # 12 output WAVs (2ch, 32-bit, 16 kHz) — committed
│   ├── speech_clean_baseline.wav
│   ├── speech_echo_baseline.wav
│   └── ...
└── update_baselines.py         # Regenerate baselines after intentional DSP changes
```


---

## 4. Step-by-Step Tasks

### Task 0: Dev Environment Setup + Spike — Verify x86 Build Works

**Goal:** (a) Create reusable bash scripts that set up the development
environment for host-based DSP testing, and (b) confirm the pipeline binary
builds and runs on x86 before investing in the full test suite. If the build
fails, stop and fix it first.

#### 0a: Create `tools/setup_dsp_host.sh`

A single script that installs all prerequisites and verifies the toolchain.
Idempotent — safe to re-run. Supports Debian/Ubuntu (apt) as primary target.

```bash
#!/usr/bin/env bash
# tools/setup_dsp_host.sh
# Sets up the host-based DSP test environment.
# Usage: bash tools/setup_dsp_host.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "=== Satellite1 XMOS: DSP Host Test Environment Setup ==="
echo "Repo root: ${REPO_ROOT}"
echo

# --- System packages (requires sudo) ---
echo "[1/5] Installing system packages..."
if command -v apt &>/dev/null; then
    PKGS=(cmake gcc g++ python3 python3-pip python3-venv)
    MISSING=()
    for pkg in "${PKGS[@]}"; do
        dpkg -s "$pkg" &>/dev/null || MISSING+=("$pkg")
    done
    if [[ ${#MISSING[@]} -gt 0 ]]; then
        echo "  Installing: ${MISSING[*]}"
        sudo apt update -qq && sudo apt install -y -qq "${MISSING[@]}"
    else
        echo "  All system packages already installed."
    fi
elif command -v dnf &>/dev/null; then
    sudo dnf install -y cmake gcc-c++ python3 python3-pip
else
    echo "  WARNING: Unknown package manager. Install manually: cmake, gcc, g++, python3, pip"
fi

# Verify cmake version
CMAKE_VER=$(cmake --version | head -1 | grep -oP '\d+\.\d+')
echo "  cmake: ${CMAKE_VER}"
if (( $(echo "${CMAKE_VER} < 3.21" | bc -l 2>/dev/null || echo 0) )); then
    echo "  ERROR: CMake >= 3.21 required, found ${CMAKE_VER}"
    exit 1
fi

# --- Python virtual environment ---
echo "[2/5] Setting up Python virtual environment..."
VENV_DIR="${REPO_ROOT}/.venv-dsp"
if [[ ! -d "${VENV_DIR}" ]]; then
    python3 -m venv "${VENV_DIR}"
    echo "  Created venv at ${VENV_DIR}"
else
    echo "  Reusing existing venv at ${VENV_DIR}"
fi
source "${VENV_DIR}/bin/activate"
pip install --quiet --upgrade pip

# --- Python dependencies ---
echo "[3/5] Installing Python packages..."
pip install --quiet \
    "xmos-ai-tools==1.3.1" \
    "numpy>=1.24" \
    "scipy>=1.10" \
    "soundfile>=0.12" \
    "pesq>=0.0.4" \
    "pytest>=7.0"
echo "  Installed: xmos-ai-tools, numpy, scipy, soundfile, pesq, pytest"

# --- Git submodules ---
echo "[4/5] Initializing git submodules..."
cd "${REPO_ROOT}"
git submodule update --init modules/voice
echo "  modules/voice: $(cd modules/voice && git log --oneline -1)"

# --- Verify toolchain ---
echo "[5/5] Verifying toolchain..."
echo "  cmake:   $(cmake --version | head -1)"
echo "  gcc:     $(gcc --version | head -1)"
echo "  python:  $(python --version)"
echo "  xcore-opt: $(which xcore-opt 2>/dev/null || echo 'NOT FOUND')"

if ! command -v xcore-opt &>/dev/null; then
    echo
    echo "  WARNING: xcore-opt not on PATH."
    echo "  The TFLite model conversion step may fail."
    echo "  Try: hash -r && which xcore-opt"
    echo "  Or:  python -m xmos_ai_tools.xcore_opt --help"
fi

# Verify TFLite Micro static lib is accessible
python -c "
import xmos_ai_tools, os
pkg_dir = os.path.dirname(xmos_ai_tools.__file__)
parent = os.path.dirname(pkg_dir)
libs = [f for f in os.walk(parent) for f in [os.path.join(dp, fn) for fn in fn_list] if 'tflite' in f.lower() and f.endswith(('.a', '.so'))]
if libs:
    print(f'  TFLite libs: {libs}')
else:
    print('  WARNING: No TFLite library files found under xmos_ai_tools')
" 2>/dev/null || echo "  (TFLite lib check skipped)"

echo
echo "=== Setup complete ==="
echo "To build:  cmake -B build-host -S modules/voice -DCMAKE_BUILD_TYPE=Release"
echo "           cmake --build build-host --target fwk_voice_example_bare_metal_pipeline_single_thread -j\$(nproc)"
echo "To test:   source .venv-dsp/bin/activate && pytest tests/test_dsp_host/ -v"
```

#### 0b: Create `tools/build_dsp_host.sh`

A build script for the DSP pipeline test binary. Separated from setup so it
can be run frequently without re-installing dependencies.

```bash
#!/usr/bin/env bash
# tools/build_dsp_host.sh
# Builds the host-compiled DSP pipeline test binary.
# Usage: bash tools/build_dsp_host.sh [--clean]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${REPO_ROOT}/build-host"
TARGET="fwk_voice_example_bare_metal_pipeline_single_thread"

if [[ "${1:-}" == "--clean" ]]; then
    echo "Cleaning build directory..."
    rm -rf "${BUILD_DIR}"
fi

# Activate venv if it exists (for xcore-opt during build)
if [[ -f "${REPO_ROOT}/.venv-dsp/bin/activate" ]]; then
    source "${REPO_ROOT}/.venv-dsp/bin/activate"
fi

# Ensure submodule is present
if [[ ! -f "${REPO_ROOT}/modules/voice/CMakeLists.txt" ]]; then
    echo "Error: modules/voice not initialized."
    echo "Run: git submodule update --init modules/voice"
    exit 1
fi

echo "Configuring..."
cmake -B "${BUILD_DIR}" -S "${REPO_ROOT}/modules/voice" -DCMAKE_BUILD_TYPE=Release

echo "Building..."
cmake --build "${BUILD_DIR}" --target "${TARGET}" -j"$(nproc)"

BINARY="${BUILD_DIR}/examples/bare-metal/pipeline_single_threaded/${TARGET}"
echo
echo "Build complete:"
ls -lh "${BINARY}"
file "${BINARY}"
```

#### 0c: Spike — Verify Build and Run

After running the setup and build scripts, verify end-to-end:

```bash
cd /path/to/Satellite1-XMOS

# 1. Set up environment
bash tools/setup_dsp_host.sh

# 2. Build the pipeline binary
bash tools/build_dsp_host.sh

# 3. Verify binary exists and is a static ELF
BINARY=build-host/examples/bare-metal/pipeline_single_threaded/fwk_voice_example_bare_metal_pipeline_single_thread
file "${BINARY}"
# Expected: "ELF 64-bit LSB executable, x86-64, ... statically linked"

# 4. Create a minimal test stimulus and run it
source .venv-dsp/bin/activate
python -c "
import numpy as np
from scipy.io import wavfile
n = 16000  # 1 second
data = np.zeros((n, 4), dtype=np.int32)
data[:, 0] = (np.sin(2*np.pi*440*np.arange(n)/16000) * 8000).astype(np.int32)
data[:, 1] = data[:, 0]
wavfile.write('/tmp/test_tone.wav', 16000, data)
"
"${BINARY}" /tmp/test_tone.wav /tmp/test_out.wav

# 5. Verify output
python -c "
from scipy.io import wavfile
import numpy as np
sr, data = wavfile.read('/tmp/test_out.wav')
rms = np.sqrt(np.mean(data.astype(np.float64)**2)) / 32768
print(f'Output: {sr} Hz, {data.shape[1]} ch, {data.shape[0]} samples, dtype={data.dtype}')
print(f'RMS: {20*np.log10(rms + 1e-12):.1f} dBFS')
assert data.shape[1] == 2, 'Expected 2 output channels'
assert data.dtype == np.int32, 'Expected int32 output'
print('PASS: Output format correct')
"

# 6. If all passes → proceed to Task 1
# 7. If build fails → investigate and fix before continuing
```

**Success criteria:**
- `tools/setup_dsp_host.sh` runs to completion without errors
- `xcore-opt` is available (on PATH or accessible via Python)
- `tools/build_dsp_host.sh` produces a static ELF binary
- Binary accepts a 4-ch 32-bit WAV and produces a 2-ch 32-bit WAV
- Output is not silent (RMS > -60 dBFS for a tone input)
- Re-running `setup_dsp_host.sh` is idempotent (no errors, no reinstall)

**If this fails:** Do NOT proceed. File an issue, investigate the build
failure, and re-run the spike until green.

---

### Task 1: CMake Wrapper (`tests/test_dsp_host/CMakeLists.txt`)

A thin CMake file that builds the fwk_voice pipeline example for x86.
Bypasses the `XCORE_XS3A` guard in `modules/CMakeLists.txt`.

```cmake
cmake_minimum_required(VERSION 3.21)
project(dsp_host_test C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 11)

set(FWK_VOICE_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/../../modules/voice)

if(NOT EXISTS "${FWK_VOICE_ROOT}/CMakeLists.txt")
    message(FATAL_ERROR
        "fwk_voice submodule not found at ${FWK_VOICE_ROOT}.\n"
        "Run: git submodule update --init modules/voice")
endif()

add_subdirectory(${FWK_VOICE_ROOT} ${CMAKE_CURRENT_BINARY_DIR}/fwk_voice)

# Copy the built binary to a stable location for pytest
add_custom_command(TARGET fwk_voice_example_bare_metal_pipeline_single_thread
    POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        $<TARGET_FILE:fwk_voice_example_bare_metal_pipeline_single_thread>
        ${CMAKE_CURRENT_BINARY_DIR}/dsp_pipeline_test
    COMMENT "Copying pipeline binary to stable location"
)
```

**Why separate CMakeLists?** The main firmware's `modules/CMakeLists.txt`
guards `add_subdirectory(voice)` behind `CMAKE_SYSTEM_NAME STREQUAL XCORE_XS3A`.
Our standalone CMake directly includes `modules/voice`, which auto-detects
non-XCORE and adds `-DX86_BUILD=1`.

**Build:**
```bash
cmake -B tests/test_dsp_host/build -S tests/test_dsp_host -DCMAKE_BUILD_TYPE=Release
cmake --build tests/test_dsp_host/build -j$(nproc)
# Binary at: tests/test_dsp_host/build/dsp_pipeline_test
```

---

### Task 2: Stimulus Generation (`tests/test_dsp_host/generate_stimuli.py`)

Generates 12 stimuli as 4-channel, 32-bit, 16 kHz WAV files.
Channel layout: `[mic1, mic2, ref1, ref2]` (first 2 = Y/mic, last 2 = X/ref).
For most stimuli, `mic2 = mic1` and `ref2 = ref1` (mono duplicated to stereo).

| File | Duration | Mic content | Ref content | Tests |
|------|----------|-------------|-------------|-------|
| `speech_clean.wav` | 30 s | Speech -6 dBFS | Silence | Baseline, PESQ (later) |
| `speech_echo.wav` | 30 s | Speech + 40 ms echo | Echo source | AEC residual, convergence |
| `speech_babble.wav` | 30 s | Speech + babble (-10 dB) | Babble | NS SNR improvement |
| `speech_quiet.wav` | 30 s | Speech -36 dBFS | Silence | AGC amplification |
| `speech_loud.wav` | 30 s | Speech +9 dBFS | Silence | AGC attenuation / clipping |
| `silence.wav` | 2 s | Silence | Silence | No noise leak (G7) |
| `noise_only.wav` | 30 s | Babble | Babble | NS on pure noise |
| `tone_sweep.wav` | 10 s | 200 Hz-8 kHz sweep | Silence | Spectral linearity |
| `impulse.wav` | 10 s | 1-sample impulse | Silence | AEC latency |
| `barge_in.wav` | 15 s | User speech from 5 s | Assistant speech | AEC under real use |
| `wake_word.wav` | 5 s | "Wake word" (placeholder) | Silence | Wake word (later) |
| `commands.wav` | 20 s | Command speech (placeholder) | Silence | WER (later) |

Total size: ~50 MB (4ch x 32-bit x 16 kHz).

**Note on wake_word/commands:** Use synthetic speech as placeholders initially.
When real TTS recordings are available (Phase 2), replace with actual
"wakeup, Satellite" and "what's the weather" recordings.

See Appendix A for the full implementation.

---

### Task 3: Pytest Fixtures (`tests/test_dsp_host/conftest.py`)

Key fixtures and helpers:
- `pipeline_binary` (session-scoped): Returns path to built binary
- `output_dir` (session-scoped): Temp directory for output WAVs
- `run_pipeline(binary, stimulus, output)`: Helper to run the binary, returns elapsed time
- `read_wav_32bit(path)`: Load WAV as int32 numpy array
- `read_wav_float(path)`: Load WAV as float32 in [-1, 1]

Supports `--dsp-binary` CLI option to override binary path.

See Appendix B for the full implementation.

---

### Task 4: Audio Metrics (`tests/test_dsp_host/metrics.py`)

| Function | Purpose |
|----------|---------|
| `rms_db(signal)` | RMS level in dBFS |
| `snr_db(signal, noise)` | Signal-to-noise ratio |
| `aec_residual_db(mic_out, ref, skip_frames)` | AEC residual echo level (lower = better) |
| `ns_snr_improvement_db(mic_in, mic_out, ref_speech)` | NS SNR improvement |
| `agc_output_level_db(signal, skip_frames)` | AGC output level after convergence |
| `log_mel_distance(sig_a, sig_b)` | Primary regression metric (0 = identical) |
| `pesq_score(reference, degraded)` | PESQ quality score (optional, needs `pesq` package) |
| `spectral_flatness(signal)` | Tonal (0) vs. noise-like (1) |
| `clipping_ratio(signal)` | Fraction of clipped samples |
| `peak_to_rms_ratio(signal)` | Crest factor |

See Appendix C for the full implementation.

---

### Task 5: Layer 1 — Binary Gates (`tests/test_dsp_host/test_dsp_gates.py`)

7 binary checks. Any failure = CI is red. No judgment required.

| Gate | Check | Stimulus | Pass condition |
|------|-------|----------|----------------|
| G1 | Pipeline produces output | speech_clean | RMS > -60 dBFS |
| G2 | No int32 overflow | speech_loud | max(abs) < 2^31 |
| G3 | AEC cancels echo | speech_echo | residual < -20 dB |
| G4 | NS doesn't degrade | speech_babble | output RMS < input RMS + 3 dB |
| G5 | AGC normalizes level | speech_clean | output in [-30, -6] dBFS |
| G6 | No excessive clipping | speech_loud | clipping < 0.1% |
| G7 | Silence stays quiet | silence | output RMS < -40 dBFS |

See Appendix D for the full implementation.

---

### Task 6: Layer 2 — Regression Delta (`tests/test_dsp_host/test_dsp_regression.py`)

For each stimulus, compare the current pipeline output against the committed
baseline output using log-mel spectral distance.

- < 3 dB mean log-mel distance = PASS
- 3-6 dB = WARNING (reported in output, doesn't fail the build)
- > 6 dB = FAIL (regression detected)

```python
def test_regression(self, pipeline_binary, output_dir):
    """Layer 2: Output must not change more than 3 dB from baseline."""
    for stim in STIMULI:
        out_path = output_dir / f"{stim.stem}_out.wav"
        run_pipeline(pipeline_binary, STIMULI_DIR / stim, out_path)
        new_data, _ = read_wav_float(out_path)
        base_data, _ = read_wav_float(BASELINE_DIR / f"{stim.stem}_baseline.wav")
        dist = log_mel_distance(new_data[:, 0], base_data[:, 0])
        assert dist < 3.0, f"REGRESSION: {stim.stem} changed {dist:.2f} dB from baseline"
```

---

### Task 7: Layer 3 — Informational Metrics (`tests/test_dsp_host/test_dsp_informational.py`)

Reported but never gates. Useful for tracking quality over time via
pytest's `record_property` mechanism (visible in CI reports).

```python
def test_informational_metrics(self, pipeline_binary, output_dir, record_property):
    """Layer 3: Report metrics for tracking (never fails)."""
    for stim, metrics in [
        ("speech_clean.wav", ["pesq", "snr", "spectral_flatness"]),
        ("speech_echo.wav", ["aec_residual", "snr"]),
        ("speech_babble.wav", ["snr_improvement", "spectral_flatness"]),
    ]:
        out_path = output_dir / f"{stim.replace('.wav', '_out.wav')}"
        run_pipeline(pipeline_binary, STIMULI_DIR / stim, out_path)
        data, _ = read_wav_float(out_path)
        for m in metrics:
            value = compute_metric(m, data, stim)
            record_property(f"{stim}:{m}", round(value, 2))
```

---

### Task 8: Baseline Management (`tests/test_dsp_host/update_baselines.py`)

Script to regenerate baselines after an intentional DSP change.

**Workflow:**
1. Make intentional DSP change (e.g., tune AGC gain)
2. Run `python update_baselines.py`
3. Review the generated baselines (listen, check metrics)
4. `git add baselines/ && git commit -m "Update DSP baselines: <reason>"`
5. CI now uses the new baselines for regression comparison

---

### Task 9: CI Integration (`.github/workflows/dsp-host-tests.yml`)

```yaml
name: DSP Host Tests

on:
  pull_request:
    paths:
      - 'satellite-xmos-firmware/**'
      - 'modules/voice/**'
      - 'tests/test_dsp_host/**'

jobs:
  dsp-tests:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install xmos-ai-tools==1.3.1
          pip install numpy scipy soundfile pesq pytest

      - name: Build pipeline binary
        run: |
          cmake -B build-host -S modules/voice -DCMAKE_BUILD_TYPE=Release
          cmake --build build-host --target fwk_voice_example_bare_metal_pipeline_single_thread -j$(nproc)

      - name: Run Layer 1 (Gates)
        run: |
          pytest tests/test_dsp_host/test_dsp_gates.py -v \
            --dsp-binary build-host/examples/bare-metal/pipeline_single_threaded/fwk_voice_example_bare_metal_pipeline_single_thread

      - name: Run Layer 2 (Regression)
        run: |
          pytest tests/test_dsp_host/test_dsp_regression.py -v \
            --dsp-binary build-host/examples/bare-metal/pipeline_single_threaded/fwk_voice_example_bare_metal_pipeline_single_thread

      - name: Run Layer 3 (Informational)
        run: |
          pytest tests/test_dsp_host/test_dsp_informational.py -v \
            --dsp-binary build-host/examples/bare-metal/pipeline_single_threaded/fwk_voice_example_bare_metal_pipeline_single_thread
```

**Expected CI time:**
- Build: ~60 s (cold) / ~10 s (warm cache)
- Layer 1: ~30 s (7 gates x ~4 s each)
- Layer 2: ~60 s (12 stimuli x ~5 s each)
- Layer 3: ~60 s (subset of stimuli)
- **Total: < 3 min** (well within 5 min budget)

---

### Task 10: .gitignore and Repo Hygiene

Add to `.gitignore`:
```
tests/test_dsp_host/build/
tests/test_dsp_host/dsp_output/
*.pyc
```

Keep in git:
```
tests/test_dsp_host/stimuli/*.wav    (~50 MB)
tests/test_dsp_host/baselines/*.wav  (~25 MB)
```

