#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
XMOS_ENV_WRAPPER="$REPO_ROOT/tools/env/xmos_env.sh"
BUILD_DIR="build_sat1_dev_xtag"
TARGET="satellite1_firmware_fixed_delay"
MODE="run"
SKIP_BUILD=0
DRY_RUN=0
DETECT_ONLY=0
ADAPTER_ID=""

usage() {
    cat <<'EOF'
Usage: tools/e2e/run_sat1_dev_xtag.sh [options]

Build and run Satellite1 firmware over xTAG (JTAG/xgdb).
This board does not use xscope in this workflow.

Options:
  --build              Build only, do not run.
  --run                Run with xrun (default).
  --debug              Run with xgdb --batch.
  --adapter-id ID      Use the given xTAG adapter id.
  --build-dir DIR      Override build directory (default: build_sat1_dev_xtag).
  --target NAME        Override firmware target (default: satellite1_firmware_fixed_delay).
  --skip-build         Do not reconfigure/rebuild before launch.
  --detect-only        Print detected adapter id and exit.
  --dry-run            Print commands without executing them.
  -h, --help           Show this help text.

Examples:
  tools/e2e/run_sat1_dev_xtag.sh --run
  tools/e2e/run_sat1_dev_xtag.sh --debug --adapter-id W256H8UD
  tools/e2e/run_sat1_dev_xtag.sh --detect-only

Env defaults:
  SAT1_XTAG_ID         Preferred default adapter id.
  XMOS_ADAPTER_ID      Backward-compatible fallback.
EOF
}

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

run_cmd() {
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '+ %s\n' "$*"
        return 0
    fi
    "$@"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --build)
            MODE="build"
            ;;
        --run)
            MODE="run"
            ;;
        --debug)
            MODE="debug"
            ;;
        --adapter-id)
            shift
            [[ $# -gt 0 ]] || die "--adapter-id requires a value"
            ADAPTER_ID="$1"
            ;;
        --build-dir)
            shift
            [[ $# -gt 0 ]] || die "--build-dir requires a value"
            BUILD_DIR="$1"
            ;;
        --target)
            shift
            [[ $# -gt 0 ]] || die "--target requires a value"
            TARGET="$1"
            ;;
        --skip-build)
            SKIP_BUILD=1
            ;;
        --detect-only)
            DETECT_ONLY=1
            ;;
        --dry-run)
            DRY_RUN=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown argument: $1"
            ;;
    esac
    shift
done

[[ -f "$XMOS_ENV_WRAPPER" ]] || die "XMOS env wrapper not found: $XMOS_ENV_WRAPPER"

cd "$REPO_ROOT"

set +u
# shellcheck disable=SC1090
source "$XMOS_ENV_WRAPPER"
set -u

if [[ -f ".venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    set +u
    source ".venv/bin/activate"
    set -u
fi

if [[ -z "$ADAPTER_ID" && -n "${SAT1_XTAG_ID:-}" ]]; then
    ADAPTER_ID="$SAT1_XTAG_ID"
fi

if [[ -z "$ADAPTER_ID" && -n "${XMOS_ADAPTER_ID:-}" ]]; then
    ADAPTER_ID="$XMOS_ADAPTER_ID"
fi

detect_adapter_id() {
    local listing ids count
    listing="$(xrun -l)"
    ids="$(printf '%s\n' "$listing" | grep -Eo '[A-Z0-9]{8}' || true)"
    count="$(printf '%s\n' "$ids" | sed '/^$/d' | wc -l | tr -d ' ')"

    if [[ "$count" -eq 0 ]]; then
        die "no XMOS adapter detected via 'xrun -l'"
    fi

    if [[ "$count" -gt 1 && -z "$ADAPTER_ID" ]]; then
        printf '%s\n' "$listing" >&2
        die "multiple adapters detected; pass --adapter-id"
    fi

    if [[ -z "$ADAPTER_ID" ]]; then
        ADAPTER_ID="$(printf '%s\n' "$ids" | sed -n '1p')"
    fi
}

detect_adapter_id

printf 'mode=%s\n' "$MODE"
printf 'build_dir=%s\n' "$BUILD_DIR"
printf 'target=%s\n' "$TARGET"
printf 'adapter_id=%s\n' "$ADAPTER_ID"

if [[ "$DETECT_ONLY" -eq 1 ]]; then
    exit 0
fi

XE_PATH="$BUILD_DIR/$TARGET.xe"

if [[ "$SKIP_BUILD" -eq 0 ]]; then
    run_cmd cmake -B "$BUILD_DIR" --toolchain xmos_cmake_toolchain/xs3a.cmake
    run_cmd cmake --build "$BUILD_DIR" -j --target "$TARGET"
fi

[[ -f "$XE_PATH" ]] || die "firmware artifact not found: $XE_PATH"

case "$MODE" in
    build)
        printf 'built=%s\n' "$XE_PATH"
        ;;
    run)
        run_cmd xrun --adapter-id "$ADAPTER_ID" "$XE_PATH"
        ;;
    debug)
        run_cmd xgdb --batch "$XE_PATH" -ex "connect --adapter-id $ADAPTER_ID --reset" -ex "run"
        ;;
    *)
        die "unexpected mode: $MODE"
        ;;
esac
