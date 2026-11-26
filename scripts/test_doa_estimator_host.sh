#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOA_OUTPUT="${TMPDIR:-/tmp}/sat1-doa-estimator-test"
BEAMFORMER_OUTPUT="${TMPDIR:-/tmp}/sat1-beamformer-test"
trap 'rm -f "${DOA_OUTPUT}" "${BEAMFORMER_OUTPUT}"' EXIT

cc \
  -std=c11 \
  -Wall \
  -Wextra \
  -Werror \
  -I "${ROOT_DIR}/satellite-xmos-firmware/src/doa" \
  "${ROOT_DIR}/tests/test_doa_estimator_host.c" \
  "${ROOT_DIR}/satellite-xmos-firmware/src/doa/doa_estimator.c" \
  -o "${DOA_OUTPUT}"

"${DOA_OUTPUT}"

cc \
  -std=c11 \
  -Wall \
  -Wextra \
  -Werror \
  -I "${ROOT_DIR}/satellite-xmos-firmware/src" \
  "${ROOT_DIR}/tests/test_sat1_beamformer_host.c" \
  "${ROOT_DIR}/satellite-xmos-firmware/src/beamforming/sat1_beamformer.c" \
  -o "${BEAMFORMER_OUTPUT}"

"${BEAMFORMER_OUTPUT}"
HINT_OUTPUT="$(mktemp)"
trap 'rm -f "${DOA_OUTPUT}" "${BEAMFORMER_OUTPUT}" "${HINT_OUTPUT}"' EXIT
cc -std=c11 -Wall -Wextra -Werror \
  -I "${ROOT_DIR}/satellite-xmos-firmware/src/doa" \
  "${ROOT_DIR}/tests/test_host_hint_lease.c" \
  "${ROOT_DIR}/satellite-xmos-firmware/src/doa/doa_estimator.c" -o "${HINT_OUTPUT}"
"${HINT_OUTPUT}"
