#!/usr/bin/env bash

# This runner intentionally only lists xTAG adapters. It never configures,
# builds, runs, flashes, or resets SQ66 firmware.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
XMOS_ENV_WRAPPER="$REPO_ROOT/tools/env/xmos_env.sh"
BUILD_DIR="build_sq66_dev"
TARGET="sq66_firmware_fixed_delay"
ADAPTER_ID=""

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

usage() {
    printf '%s\n' 'Usage: tools/e2e/run_sq66_detect_only.sh [--adapter-id ID] [--detect-only]'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --adapter-id)
            shift
            [[ $# -gt 0 ]] || die "--adapter-id requires a value"
            ADAPTER_ID="$1"
            ;;
        --detect-only)
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "detect-only runner does not support: $1"
            ;;
    esac
    shift
done

[[ -f "$XMOS_ENV_WRAPPER" ]] || die "XMOS env wrapper not found: $XMOS_ENV_WRAPPER"
# shellcheck disable=SC1090
source "$XMOS_ENV_WRAPPER"

if [[ -z "$ADAPTER_ID" ]]; then
    ADAPTER_ID="${SQ66_XTAG_ID:-${XMOS_ADAPTER_ID:-}}"
fi

listing="$(xrun -l)"
adapter_ids=()
while IFS= read -r adapter_id; do
    [[ -n "$adapter_id" ]] && adapter_ids+=("$adapter_id")
done < <(printf '%s\n' "$listing" | grep -Eo '[A-Z0-9]{8}' || true)

if [[ ${#adapter_ids[@]} -eq 0 ]]; then
    die "no XMOS adapter detected via 'xrun -l'"
fi

if [[ -z "$ADAPTER_ID" ]]; then
    if [[ ${#adapter_ids[@]} -gt 1 ]]; then
        printf '%s\n' "$listing" >&2
        die "multiple adapters detected; set SQ66_XTAG_ID or pass --adapter-id"
    fi
    ADAPTER_ID="${adapter_ids[0]}"
fi

printf 'mode=run\n'
printf 'build_dir=%s\n' "$BUILD_DIR"
printf 'target=%s\n' "$TARGET"
printf 'adapter_id=%s\n' "$ADAPTER_ID"
