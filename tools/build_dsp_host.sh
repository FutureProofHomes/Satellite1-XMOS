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

# Patch flatbuffers header for GCC >= 13 (const member assignment error)
FLATBUFFERS_H=$(python -c "
import xmos_ai_tools, os
pkg_dir = os.path.dirname(xmos_ai_tools.__file__)
print(os.path.join(pkg_dir, 'runtime', 'include', 'flatbuffers', 'stl_emulation.h'))
" 2>/dev/null)
if [[ -n "${FLATBUFFERS_H}" && -f "${FLATBUFFERS_H}" ]]; then
    if grep -q 'count_ = other.count_;' "${FLATBUFFERS_H}"; then
        echo "Patching flatbuffers stl_emulation.h for GCC compatibility..."
        sed -i 's/    count_ = other.count_;/    \/\/ count_ is const; no-op/' "${FLATBUFFERS_H}"
    fi
fi

echo "Configuring..."
cmake -B "${BUILD_DIR}" -S "${REPO_ROOT}/modules/voice" -DCMAKE_BUILD_TYPE=Release

echo "Building..."
cmake --build "${BUILD_DIR}" --target "${TARGET}" -j"$(nproc)"

BINARY="${BUILD_DIR}/examples/bare-metal/pipeline_single_threaded/bin/${TARGET}"
echo
echo "Build complete:"
ls -lh "${BINARY}"
file "${BINARY}"
