#!/bin/sh
# Builds the speaker EQ tests for xsim and checks them against the Python model.
# Needs the XTC tools on PATH and a configured firmware build (for the
# lib_audio_dsp and lib_xcore_math archives): make -C build lib_audio_dsp
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../.." && pwd)
BUILD=${BUILD_DIR:-$ROOT/build}
OUT=$BUILD/speaker_eq_test
SRC=$ROOT/satellite-xmos-firmware/src

mkdir -p "$OUT"
xcc -target=XCORE-AI-EXPLORER -Os -g -DTHIS_XCORE_TILE=0 \
    -I"$HERE/stubs" \
    -I"$SRC" \
    -I"$ROOT/modules/core/modules/multitile_support/api" \
    -I"$ROOT/modules/audio_dsp/lib_audio_dsp/lib_audio_dsp/api" \
    -I"$ROOT/modules/core/modules/xcore_math/lib_xcore_math/lib_xcore_math/api" \
    "$HERE/test_speaker_eq.c" \
    "$SRC/speaker_eq/speaker_eq.c" \
    "$SRC/speaker_eq/speaker_eq_design.c" \
    "$BUILD/modules/audio_dsp/liblib_audio_dsp.a" \
    "$BUILD/modules/core/modules/xcore_math/lib_xcore_math/lib_xcore_math/liblib_xcore_math.a" \
    -o "$OUT/test_speaker_eq.xe"

echo "Running xsim (log: $OUT/xsim.log)"
xsim "$OUT/test_speaker_eq.xe" | tee "$OUT/xsim.log" || true
echo "Checking against the Python model"
python3 "$HERE/check_speaker_eq.py" "$OUT/xsim.log"
