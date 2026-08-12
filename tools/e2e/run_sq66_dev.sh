#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
XMOS_ENV_WRAPPER="$REPO_ROOT/tools/env/xmos_env.sh"
BUILD_DIR="build_sq66_dev"
TARGET="sq66_firmware_fixed_delay"
MODE="run"
SKIP_BUILD=0
DRY_RUN=0
DETECT_ONLY=0
ADAPTER_ID=""
ADAPTER_ID_CONFIGURED=0

usage() {
    cat <<'EOF'
Usage: tools/e2e/run_sq66_dev.sh [options]

Build and run the SQ66 dev-mode firmware with xscope or xgdb.

Options:
  --build              Build only, do not run.
  --run                Run with xrun --xscope (default).
  --debug              Run with xgdb --batch.
  --adapter-id ID      Use the given xTAG adapter id.
  --build-dir DIR      Override the build directory (default: build_sq66_dev).
  --target NAME        Override the firmware target (default: sq66_firmware_fixed_delay).
  --skip-build         Do not reconfigure/rebuild before launch.
  --detect-only        Print the detected adapter id and exit.
  --dry-run            Print build/run commands without executing them.
  -h, --help           Show this help text.

Env defaults:
   SQ66_XTAG_ID         Preferred default adapter id.
   XMOS_ADAPTER_ID      Backward-compatible fallback.
   SQ66_ALLOW_DIRTY_BUILD=1
                       Allow versioning from a dirty source tree. Default is off.
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
        --build) MODE="build" ;;
        --run) MODE="run" ;;
        --debug) MODE="debug" ;;
        --adapter-id)
            shift
            [[ $# -gt 0 ]] || die "--adapter-id requires a value"
            ADAPTER_ID="$1"
            ADAPTER_ID_CONFIGURED=1
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
        --skip-build) SKIP_BUILD=1 ;;
        --detect-only) DETECT_ONLY=1 ;;
        --dry-run) DRY_RUN=1 ;;
        -h|--help)
            usage
            exit 0
            ;;
        *) die "unknown argument: $1" ;;
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
    set +u
    # shellcheck disable=SC1091
    source ".venv/bin/activate"
    set -u
fi

if [[ -z "$ADAPTER_ID" && -n "${SQ66_XTAG_ID:-}" ]]; then
    ADAPTER_ID="$SQ66_XTAG_ID"
    ADAPTER_ID_CONFIGURED=1
fi
if [[ -z "$ADAPTER_ID" && -n "${XMOS_ADAPTER_ID:-}" ]]; then
    ADAPTER_ID="$XMOS_ADAPTER_ID"
    ADAPTER_ID_CONFIGURED=1
fi

detect_adapter_id() {
    local listing adapter_id count
    listing="$(xrun -l)"
    count=0

    # Do not use mapfile: macOS ships Bash 3.2.  Keep the first detected id
    # while counting all ids so that an ambiguous adapter selection is safe.
    while IFS= read -r adapter_id; do
        [[ -n "$adapter_id" ]] || continue
        count=$((count + 1))
        if [[ -z "$ADAPTER_ID" && "$count" -eq 1 ]]; then
            ADAPTER_ID="$adapter_id"
        fi
    done < <(printf '%s\n' "$listing" | grep -Eo '[A-Z0-9]{8}' || true)

    if [[ "$count" -eq 0 ]]; then
        die "no XMOS adapter detected via 'xrun -l'"
    fi
    if [[ "$count" -gt 1 && "$ADAPTER_ID_CONFIGURED" -eq 0 ]]; then
        printf '%s\n' "$listing" >&2
        die "multiple adapters detected; pass --adapter-id"
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
    cmake_args=(-DUSE_DEV_MODE=ON)
    if [[ "${SQ66_ALLOW_DIRTY_BUILD:-}" == "1" ]]; then
        cmake_args+=(-DALLOW_DIRTY_VERSIONING=ON)
    fi
    run_cmd cmake -B "$BUILD_DIR" --toolchain xmos_cmake_toolchain/xs3a.cmake "${cmake_args[@]}"
    run_cmd cmake --build "$BUILD_DIR" -j --target "$TARGET"
fi

[[ -f "$XE_PATH" ]] || die "firmware artifact not found: $XE_PATH"

stale_xmos_processes() {
    local pid command
    while read -r pid command; do
        if [[ "$command" =~ (^|/)x(run|gdb|gdbserver)([[:space:]]|$) ]]; then
            printf '%s %s\n' "$pid" "$command"
        fi
    done < <(ps -ax -o pid= -o command=)
}

case "$MODE" in
    build)
        printf 'built=%s\n' "$XE_PATH"
        ;;
    run|debug)
        stale_processes="$(stale_xmos_processes)"
        if [[ -n "$stale_processes" ]]; then
            die "stale xrun/xgdb/xgdbserver process(es) detected; stop them before launching:\n$stale_processes"
        fi
        if [[ "$MODE" == "run" ]]; then
            run_cmd xrun --adapter-id "$ADAPTER_ID" --xscope "$XE_PATH"
        else
            run_cmd xgdb --batch "$XE_PATH" -ex "connect --adapter-id $ADAPTER_ID --xscope --reset" -ex "run"
        fi
        ;;
    *) die "unexpected mode: $MODE" ;;
esac
