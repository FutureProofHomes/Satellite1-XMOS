#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# If SAT1_RPI_HOST is not exported in the shell, try loading repo-local .env.
if [[ -z "${SAT1_RPI_HOST:-}" && -f "$REPO_ROOT/.env" ]]; then
    # shellcheck disable=SC1090
    set -a
    source "$REPO_ROOT/.env"
    set +a
fi

HOST="${SAT1_RPI_HOST:-}"
ANGLES_DEG="30,90,150,-90"
SEGMENT_S="3"
POLL_S="0.1"
APLAY_DEV="hw:0,0"
SHOW_PLOT=0
KEEP_FILES=0
RUN_HIL=1
REMOTE_WAV=""
HIL_REPORT=""

RUN_ID="$(date +%Y%m%d_%H%M%S)"
LOCAL_WAV="/tmp/doa_fixture_lagsynth_${RUN_ID}.wav"
LOCAL_EXPECTED="/tmp/doa_fixture_lagsynth_${RUN_ID}.expected.json"
LOCAL_LAGS="/tmp/doa_fixture_lagsynth_${RUN_ID}.lags.csv"

usage() {
    cat <<'EOF'
Usage: tools/e2e/run_doa_fixture_hil.sh [options]

Generate a deterministic DoA fixture WAV (lag-synth), validate it with
doa_gcc_phat_test, and optionally run HIL injection/plot demo.

Options:
  --host HOST             SSH host for HIL demo (default: SAT1_RPI_HOST)
  --angles-deg CSV        Segment angles (default: 30,90,150,-90)
  --segment-s SEC         Seconds per segment (default: 3)
  --poll-s SEC            Plot polling interval (default: 0.1)
  --aplay-dev DEV         ALSA playback device (default: hw:0,0)
  --remote-wav PATH       Remote WAV path override
  --show-plot             Show GUI plot window during HIL eval
  --hil-report PATH       Output JSON path for HIL eval report
  --no-hil                Only generate fixture + run local unit test
  --keep-files            Keep generated local fixture files in /tmp
  -h, --help              Show this help
EOF
}

cleanup() {
    if [[ "$KEEP_FILES" -eq 0 ]]; then
        rm -f "$LOCAL_WAV" "$LOCAL_EXPECTED" "$LOCAL_LAGS"
    fi
}

trap cleanup EXIT

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            shift
            HOST="${1:-}"
            ;;
        --angles-deg)
            shift
            ANGLES_DEG="${1:-}"
            ;;
        --segment-s)
            shift
            SEGMENT_S="${1:-}"
            ;;
        --source)
            shift
            ;;
        --poll-s)
            shift
            POLL_S="${1:-}"
            ;;
        --aplay-dev)
            shift
            APLAY_DEV="${1:-}"
            ;;
        --remote-wav)
            shift
            REMOTE_WAV="${1:-}"
            ;;
        --expected-offset-deg)
            shift
            ;;
        --show-plot)
            SHOW_PLOT=1
            ;;
        --hil-report)
            shift
            HIL_REPORT="${1:-}"
            ;;
        --no-hil)
            RUN_HIL=0
            ;;
        --keep-files)
            KEEP_FILES=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'error: unknown argument: %s\n' "$1" >&2
            usage
            exit 2
            ;;
    esac
    shift
done

printf 'Generating deterministic fixture WAV...\n'
python3 "$REPO_ROOT/tools/doa/generate_doa_fixture_set.py" \
    --angles-deg "$ANGLES_DEG" \
    --segment-s "$SEGMENT_S" \
    --out-wav "$LOCAL_WAV" \
    --out-expected "$LOCAL_EXPECTED" \
    --out-lag-fixture "$LOCAL_LAGS"

printf 'Building DoA unit tests...\n'
cmake -S "$REPO_ROOT/modules/fph/doa/tests" -B "$REPO_ROOT/build_doa_tests"
cmake --build "$REPO_ROOT/build_doa_tests" -j

printf 'Validating fixture WAV with doa_gcc_phat_test...\n'
"$REPO_ROOT/build_doa_tests/doa_gcc_phat_test" --wav "$LOCAL_WAV"

printf 'Fixture WAV: %s\n' "$LOCAL_WAV"
printf 'Fixture expected JSON: %s\n' "$LOCAL_EXPECTED"
printf 'Fixture lag CSV: %s\n' "$LOCAL_LAGS"

if [[ "$RUN_HIL" -eq 0 ]]; then
    printf 'Skipping HIL (--no-hil).\n'
    exit 0
fi

if [[ -z "$HOST" ]]; then
    printf 'error: --host is required for HIL run (or set SAT1_RPI_HOST)\n' >&2
    exit 2
fi

printf 'Starting HIL demo with lag-synth fixture settings...\n'
if [[ -z "$HIL_REPORT" ]]; then
    HIL_REPORT="/tmp/doa_fixture_lagsynth_${RUN_ID}.hil.json"
fi

CMD=(
    python3 "$REPO_ROOT/tools/e2e/run_doa_wav_hil_eval.py"
    --host "$HOST"
    --wav "$LOCAL_WAV"
    --expected-file "$LOCAL_EXPECTED"
    --poll-s "$POLL_S"
    --aplay-dev "$APLAY_DEV"
    --out-json "$HIL_REPORT"
    --auto-offset
)

if [[ -n "$REMOTE_WAV" ]]; then
    CMD+=(--remote-wav "$REMOTE_WAV")
fi

if [[ "$SHOW_PLOT" -eq 1 ]]; then
    CMD+=(--show-plot)
fi

if [[ "$KEEP_FILES" -eq 1 ]]; then
    CMD+=(--keep-files)
fi

"${CMD[@]}"

printf 'HIL report: %s\n' "$HIL_REPORT"
