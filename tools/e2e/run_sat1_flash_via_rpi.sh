#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
XMOS_ENV_WRAPPER="$REPO_ROOT/tools/env/xmos_env.sh"

BUILD_DIR="build_SATELLITE1"
TARGET="satellite1_firmware_fixed_delay"
MODE="all"
SKIP_BUILD=0
DRY_RUN=0
RPI_HOST="${SAT1_RPI_HOST:-}"
SAT1_CMD="${SAT1_RPI_SAT1_CMD:-sat1}"
FACTORY_BIN=""
REMOTE_PATH=""
SSH_CONNECT_TIMEOUT_S="${SAT1_FLASH_SSH_CONNECT_TIMEOUT_S:-5}"
REMOTE_SUDO="${SAT1_FLASH_REMOTE_SUDO:-0}"

usage() {
    cat <<'EOF'
Usage: tools/e2e/run_sat1_flash_via_rpi.sh [options]

Build and/or flash Satellite1 factory image via Pi-side sat1 CLI.

Modes (default: --all):
  --all                Build, flash, then verify firmware.
  --build              Build only (create factory image).
  --flash              Flash only (requires local .factory.bin).
  --verify             Verify only via 'sat1 xmos read-firmware'.

Options:
  --rpi-host HOST      Pi SSH host (default: SAT1_RPI_HOST env var).
  --sat1-cmd CMD       Remote sat1 command (default: SAT1_RPI_SAT1_CMD or 'sat1').
  --build-dir DIR      Build directory (default: build_SATELLITE1).
  --target NAME        Firmware target (default: satellite1_firmware_fixed_delay).
  --factory-bin PATH   Local factory image path (must end with .factory.bin).
  --remote-path PATH   Remote path for uploaded factory image.
  --skip-build         Skip configure/build during --all mode.
  --remote-sudo        Run remote flash command with 'sudo -n'.
  --dry-run            Print commands without executing them.
  -h, --help           Show this help text.

Examples:
  tools/e2e/run_sat1_flash_via_rpi.sh --all --rpi-host pi@192.168.1.22
  tools/e2e/run_sat1_flash_via_rpi.sh --build
  tools/e2e/run_sat1_flash_via_rpi.sh --flash --rpi-host pi@192.168.1.22 --factory-bin build_SATELLITE1/satellite1_firmware_fixed_delay.factory.bin
  SAT1_FLASH_REMOTE_SUDO=1 tools/e2e/run_sat1_flash_via_rpi.sh --flash --rpi-host pi@192.168.1.22
  tools/e2e/run_sat1_flash_via_rpi.sh --verify --rpi-host pi@192.168.1.22
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
        --all)
            MODE="all"
            ;;
        --build)
            MODE="build"
            ;;
        --flash)
            MODE="flash"
            ;;
        --verify)
            MODE="verify"
            ;;
        --rpi-host)
            shift
            [[ $# -gt 0 ]] || die "--rpi-host requires a value"
            RPI_HOST="$1"
            ;;
        --sat1-cmd)
            shift
            [[ $# -gt 0 ]] || die "--sat1-cmd requires a value"
            SAT1_CMD="$1"
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
        --factory-bin)
            shift
            [[ $# -gt 0 ]] || die "--factory-bin requires a value"
            FACTORY_BIN="$1"
            ;;
        --remote-path)
            shift
            [[ $# -gt 0 ]] || die "--remote-path requires a value"
            REMOTE_PATH="$1"
            ;;
        --skip-build)
            SKIP_BUILD=1
            ;;
        --remote-sudo)
            REMOTE_SUDO=1
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

cd "$REPO_ROOT"

NEEDS_XMOS_ENV=0
if [[ "$MODE" == "build" || ( "$MODE" == "all" && "$SKIP_BUILD" -eq 0 ) ]]; then
    NEEDS_XMOS_ENV=1
fi

if [[ "$NEEDS_XMOS_ENV" -eq 1 ]]; then
    [[ -f "$XMOS_ENV_WRAPPER" ]] || die "XMOS env wrapper not found: $XMOS_ENV_WRAPPER"

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
fi

if [[ -z "$FACTORY_BIN" ]]; then
    FACTORY_BIN="$BUILD_DIR/$TARGET.factory.bin"
fi

if [[ -z "$REMOTE_PATH" ]]; then
    REMOTE_PATH="/tmp/$TARGET.factory.bin"
fi

case "$FACTORY_BIN" in
    *.factory.bin)
        ;;
    *)
        die "only factory images are supported; expected a .factory.bin path"
        ;;
esac

if [[ "$MODE" != "build" && -z "$RPI_HOST" ]]; then
    die "--rpi-host (or SAT1_RPI_HOST) is required for flash/verify modes"
fi

printf 'mode=%s\n' "$MODE"
printf 'build_dir=%s\n' "$BUILD_DIR"
printf 'target=%s\n' "$TARGET"
printf 'factory_bin=%s\n' "$FACTORY_BIN"
printf 'rpi_host=%s\n' "${RPI_HOST:-<none>}"
printf 'sat1_cmd=%s\n' "$SAT1_CMD"
printf 'remote_path=%s\n' "$REMOTE_PATH"
printf 'remote_sudo=%s\n' "$REMOTE_SUDO"

remote_preflight_flashrom() {
    local user_flashrom sudo_flashrom

    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '+ %s\n' "ssh -o BatchMode=yes -o ConnectTimeout=$SSH_CONNECT_TIMEOUT_S $RPI_HOST command -v flashrom"
        printf '+ %s\n' "ssh -o BatchMode=yes -o ConnectTimeout=$SSH_CONNECT_TIMEOUT_S $RPI_HOST sudo -n sh -lc 'command -v flashrom'"
        return 0
    fi

    user_flashrom="$(ssh -o BatchMode=yes -o "ConnectTimeout=$SSH_CONNECT_TIMEOUT_S" "$RPI_HOST" "command -v flashrom || true")"
    sudo_flashrom="$(ssh -o BatchMode=yes -o "ConnectTimeout=$SSH_CONNECT_TIMEOUT_S" "$RPI_HOST" "sudo -n sh -lc 'command -v flashrom || true'")"

    if [[ -n "${user_flashrom//[[:space:]]/}" ]]; then
        printf 'remote_flashrom_user=%s\n' "$user_flashrom"
    else
        printf 'remote_flashrom_user=<not-found>\n'
    fi

    if [[ -n "${sudo_flashrom//[[:space:]]/}" ]]; then
        printf 'remote_flashrom_sudo=%s\n' "$sudo_flashrom"
    else
        printf 'remote_flashrom_sudo=<not-found>\n'
    fi

    if [[ -z "${user_flashrom//[[:space:]]/}" && -n "${sudo_flashrom//[[:space:]]/}" ]]; then
        printf 'note: flashrom found only under sudo path; use --remote-sudo if flashing fails\n'
    fi
}

do_build() {
    local flash_target
    flash_target="create_flash_img_$TARGET"
    run_cmd cmake -B "$BUILD_DIR" --toolchain xmos_cmake_toolchain/xs3a.cmake -DBOARD=SATELLITE1
    run_cmd cmake --build "$BUILD_DIR" -j --target "$flash_target"
    if [[ "$DRY_RUN" -eq 0 ]]; then
        [[ -f "$FACTORY_BIN" ]] || die "factory image not found after build: $FACTORY_BIN"
    fi
}

do_flash() {
    local remote_cmd

    if [[ "$DRY_RUN" -eq 0 ]]; then
        [[ -f "$FACTORY_BIN" ]] || die "factory image not found: $FACTORY_BIN"
    fi
    run_cmd scp "$FACTORY_BIN" "$RPI_HOST:$REMOTE_PATH"

    remote_preflight_flashrom

    remote_cmd="$SAT1_CMD xmos flash-firmware $REMOTE_PATH"
    if [[ "$REMOTE_SUDO" -eq 1 ]]; then
        remote_cmd="sudo -n $remote_cmd"
    fi
    run_cmd ssh -o BatchMode=yes -o "ConnectTimeout=$SSH_CONNECT_TIMEOUT_S" "$RPI_HOST" "$remote_cmd"
}

do_verify() {
    local remote_cmd verify_out
    remote_cmd="$SAT1_CMD xmos read-firmware"

    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '+ %s\n' "ssh -o BatchMode=yes -o ConnectTimeout=$SSH_CONNECT_TIMEOUT_S $RPI_HOST $remote_cmd"
        return 0
    fi

    verify_out="$(ssh -o BatchMode=yes -o "ConnectTimeout=$SSH_CONNECT_TIMEOUT_S" "$RPI_HOST" "$remote_cmd")"
    verify_out="${verify_out##$'\n'}"
    if [[ -z "${verify_out//[[:space:]]/}" || "$verify_out" == "None" ]]; then
        die "firmware verification returned empty output"
    fi
    printf 'verified_firmware=%s\n' "$verify_out"
}

case "$MODE" in
    all)
        if [[ "$SKIP_BUILD" -eq 0 ]]; then
            do_build
        else
            if [[ "$DRY_RUN" -eq 0 ]]; then
                [[ -f "$FACTORY_BIN" ]] || die "--skip-build used but factory image missing: $FACTORY_BIN"
            fi
        fi
        do_flash
        do_verify
        ;;
    build)
        do_build
        ;;
    flash)
        do_flash
        ;;
    verify)
        do_verify
        ;;
    *)
        die "unexpected mode: $MODE"
        ;;
esac
