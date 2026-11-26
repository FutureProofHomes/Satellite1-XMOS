#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${1:-calibrated_beam}"
case "${PROFILE}" in
  speech_tracking) TARGET=speech_tracking; DOA=ON; DEFAULT_VERSION=v1.2.0-dev.16 ;;
  upstream) TARGET=fixed_delay; DOA=OFF; DEFAULT_VERSION=v1.2.0-dev.19 ;;
  diagnostics) TARGET=fixed_delay; DOA=ON; DEFAULT_VERSION=v1.2.0-dev.18 ;;
  calibrated_beam) TARGET=calibrated_beam; DOA=ON; DEFAULT_VERSION=v1.2.0-dev.17 ;;
  *) echo "Usage: $0 [upstream|diagnostics|calibrated_beam|speech_tracking]" >&2; exit 2 ;;
esac

if [[ -n "${XMOS_TOOL_PATH:-}" && -f "${XMOS_TOOL_PATH}/SetEnv.sh" ]]; then
  set +u
  source "${XMOS_TOOL_PATH}/SetEnv.sh"
  set -u
elif [[ -f /Applications/XMOS_XTC_15.3.1/SetEnv.sh ]]; then
  set +u
  source /Applications/XMOS_XTC_15.3.1/SetEnv.sh
  set -u
fi
command -v xcc >/dev/null || { echo "Activate XMOS XTC 15.3.1 first." >&2; exit 1; }

PYTHON_BIN="${PYTHON_BIN:-python3.11}"
CMAKE_BIN="${CMAKE_BIN:-cmake}"
NINJA_BIN="${NINJA_BIN:-ninja}"
if [[ ! -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  "${PYTHON_BIN}" -m venv "${ROOT_DIR}/.venv"
fi
# The upstream XCORE builder image includes Make but does not include Ninja.
"${ROOT_DIR}/.venv/bin/python" -m pip install -r "${ROOT_DIR}/requirements.txt" "ninja==1.11.1.1"
export PATH="${ROOT_DIR}/.venv/bin:${PATH}"
export LC_ALL=C
BUILD_DIR="${ROOT_DIR}/build_${PROFILE}"
"${CMAKE_BIN}" -S "${ROOT_DIR}" -B "${BUILD_DIR}" -G Ninja \
  --toolchain "${ROOT_DIR}/xmos_cmake_toolchain/xs3a.cmake" \
  -DCMAKE_MAKE_PROGRAM="$(command -v "${NINJA_BIN}")" \
  -DPython3_EXECUTABLE="${ROOT_DIR}/.venv/bin/python" \
  -DENABLE_SAT1_DIRECTION_FINDING="${DOA}" \
  -DSAT1_FIRMWARE_VERSION="${SAT1_FIRMWARE_VERSION:-${DEFAULT_VERSION}}" \
  -DALLOW_DIRTY_VERSIONING=ON -DBUILD_VOICE_COMPAT_TESTS=ON
"${CMAKE_BIN}" --build "${BUILD_DIR}" --target "create_flash_img_satellite1_firmware_${TARGET}"
if [[ "${SAT1_RUN_SIM_TESTS:-1}" == "1" ]]; then
  "${CMAKE_BIN}" --build "${BUILD_DIR}" --target voice_compat_test
  SIM_IMAGE="$(find "${BUILD_DIR}" -name voice_compat_test.xe -print -quit)"
  xsim "${SIM_IMAGE}"
  if [[ "${PROFILE}" == speech_tracking ]]; then
    "${CMAKE_BIN}" --build "${BUILD_DIR}" --target sat1_voice_frontend_test
    xsim "${BUILD_DIR}/satellite-xmos-firmware/audio_pipelines/sat1_voice_frontend_test.xe"
  fi
fi
printf 'Image: %s\n' "${BUILD_DIR}/satellite1_firmware_${TARGET}.factory.bin"
printf 'MD5:   %s\n' "${BUILD_DIR}/satellite1_firmware_${TARGET}.factory.md5"
