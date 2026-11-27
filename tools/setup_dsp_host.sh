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

# Verify cmake version (fall back to pip-installed cmake if system cmake missing)
if ! command -v cmake &>/dev/null; then
    echo "  System cmake not found. Will install via pip into venv."
    CMAKE_VIA_PIP=1
else
    CMAKE_VIA_PIP=0
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
# Note: xmos-ai-tools requires numpy<2.0, so scipy must be <1.15 (scipy>=1.15
# requires numpy>=2.0). Use scipy 1.14.x which has prebuilt wheels for Py3.12+.
PIP_PKGS=(
    "xmos-ai-tools==1.3.1"
    "numpy>=1.24,<2.0"
    "scipy>=1.10,<1.15"
    "soundfile>=0.12"
    "pesq>=0.0.4"
    "pytest>=7.0"
)
if [[ "${CMAKE_VIA_PIP}" == "1" ]]; then
    PIP_PKGS+=("cmake>=3.21")
fi
pip install --quiet "${PIP_PKGS[@]}"
echo "  Installed: xmos-ai-tools, numpy, scipy, soundfile, pesq, pytest${CMAKE_VIA_PIP:+, cmake}"

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
echo "  numpy:   $(python -c 'import numpy; print(numpy.__version__)')"
echo "  scipy:   $(python -c 'import scipy; print(scipy.__version__)')"

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
libs = [os.path.join(dp, fn) for dp, dn, fn_list in os.walk(parent) for fn in fn_list if 'tflite' in fn.lower() and fn.endswith(('.a', '.so'))]
if libs:
    print(f'  TFLite libs found: {len(libs)}')
    for lib in libs[:5]:
        print(f'    {lib}')
else:
    print('  WARNING: No TFLite library files found under xmos_ai_tools')
" 2>/dev/null || echo "  (TFLite lib check skipped)"

echo
echo "=== Setup complete ==="
echo "To build:  bash tools/build_dsp_host.sh"
echo "To test:   source .venv-dsp/bin/activate && pytest tests/test_dsp_host/ -v"
