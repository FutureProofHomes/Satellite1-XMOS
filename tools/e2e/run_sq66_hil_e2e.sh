#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
XMOS_ENV_WRAPPER="$REPO_ROOT/tools/env/xmos_env.sh"

MODE="full"
DRY_RUN=0
FAIL_FAST=1
REQUIRE_NO_SKIP=1
ENABLE_OPTIONAL_TESTS=1
RUN_FIRMWARE="${SQ66_HIL_RUN_FIRMWARE:-1}"
RUN_MODE="${SQ66_HIL_RUN_MODE:-run}"
SQ66_RPI_HOST_ARG="${SQ66_RPI_HOST:-}"
SQ66_RPI_CLI_CMD_ARG="${SQ66_RPI_CLI_CMD:-sat1}"
SQ66_RPI_PY_CMD_ARG="${SQ66_RPI_PY_CMD:-/opt/satellite1/venv/bin/python}"
PYTHON_BIN=""
PYTEST_EXTRA_ARGS=()

usage() {
    cat <<'EOF'
Usage: tools/e2e/run_sq66_hil_e2e.sh [options] [-- <extra pytest args>]

Run full SQ66 HIL pytest suites with fail-fast and skip policy controls.

Modes (default: --full):
  --full                Run tests/test_hil and tests/test_hw_sq66_firmware.
  --smoke               Run only SQ66 smoke test file.

Behavior options:
  --allow-skips         Do not fail run when tests are skipped.
  --no-fail-fast        Disable pytest fail-fast (-x).
  --disable-optional    Do not auto-enable optional SQ66 DoA playback gates.
  --run-firmware        Enable SQ66 runner fixture during pytest.
  --no-run-firmware     Do not auto-run SQ66 firmware.
  --run-mode MODE       Runner mode: run|debug (default from SQ66_HIL_RUN_MODE or run).
  --python-bin PATH     Python executable for pytest (default: .venv/bin/python if present, else python3).
  --dry-run             Print commands without executing them.

Remote target options:
  --rpi-host HOST       Override SQ66_RPI_HOST.
  --sq66-cmd CMD        Override SQ66_RPI_CLI_CMD.
  --sq66-py-cmd CMD     Override SQ66_RPI_PY_CMD.

Examples:
  tools/e2e/run_sq66_hil_e2e.sh --full
  tools/e2e/run_sq66_hil_e2e.sh --smoke
  tools/e2e/run_sq66_hil_e2e.sh --full --allow-skips
  tools/e2e/run_sq66_hil_e2e.sh --full --run-mode debug
  tools/e2e/run_sq66_hil_e2e.sh --full -- --maxfail=1 -k doa
EOF
}

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --full)
            MODE="full"
            ;;
        --smoke)
            MODE="smoke"
            ;;
        --allow-skips)
            REQUIRE_NO_SKIP=0
            ;;
        --no-fail-fast)
            FAIL_FAST=0
            ;;
        --disable-optional)
            ENABLE_OPTIONAL_TESTS=0
            ;;
        --run-firmware)
            RUN_FIRMWARE=1
            ;;
        --no-run-firmware)
            RUN_FIRMWARE=0
            ;;
        --run-mode)
            shift
            [[ $# -gt 0 ]] || die "--run-mode requires a value"
            RUN_MODE="$1"
            ;;
        --python-bin)
            shift
            [[ $# -gt 0 ]] || die "--python-bin requires a value"
            PYTHON_BIN="$1"
            ;;
        --rpi-host)
            shift
            [[ $# -gt 0 ]] || die "--rpi-host requires a value"
            SQ66_RPI_HOST_ARG="$1"
            ;;
        --sq66-cmd)
            shift
            [[ $# -gt 0 ]] || die "--sq66-cmd requires a value"
            SQ66_RPI_CLI_CMD_ARG="$1"
            ;;
        --sq66-py-cmd)
            shift
            [[ $# -gt 0 ]] || die "--sq66-py-cmd requires a value"
            SQ66_RPI_PY_CMD_ARG="$1"
            ;;
        --dry-run)
            DRY_RUN=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            while [[ $# -gt 0 ]]; do
                PYTEST_EXTRA_ARGS+=("$1")
                shift
            done
            break
            ;;
        *)
            die "unknown argument: $1"
            ;;
    esac
    shift
done

if [[ "$RUN_MODE" != "run" && "$RUN_MODE" != "debug" ]]; then
    die "--run-mode must be 'run' or 'debug'"
fi

cd "$REPO_ROOT"
[[ -f "$XMOS_ENV_WRAPPER" ]] || die "XMOS env wrapper not found: $XMOS_ENV_WRAPPER"

set +u
# shellcheck disable=SC1090
source "$XMOS_ENV_WRAPPER"
set -u

if [[ -z "${SQ66_RPI_HOST_ARG:-}" && -f "$REPO_ROOT/.env" ]]; then
    set +u
    # shellcheck disable=SC1090
    source "$REPO_ROOT/.env"
    set -u
    SQ66_RPI_HOST_ARG="${SQ66_RPI_HOST:-}"
    SQ66_RPI_CLI_CMD_ARG="${SQ66_RPI_CLI_CMD:-$SQ66_RPI_CLI_CMD_ARG}"
    SQ66_RPI_PY_CMD_ARG="${SQ66_RPI_PY_CMD:-$SQ66_RPI_PY_CMD_ARG}"
fi

if [[ -z "${SQ66_RPI_HOST_ARG:-}" ]]; then
    die "--rpi-host (or SQ66_RPI_HOST via xmos_env/.env) is required"
fi

export SAT1_HIL=0
export SQ66_HIL=1
export SQ66_RPI_HOST="$SQ66_RPI_HOST_ARG"
export SQ66_RPI_CLI_CMD="$SQ66_RPI_CLI_CMD_ARG"
export SQ66_RPI_PY_CMD="$SQ66_RPI_PY_CMD_ARG"
export SQ66_HIL_RUN_FIRMWARE="$RUN_FIRMWARE"
export SQ66_HIL_RUN_MODE="$RUN_MODE"

if [[ "$ENABLE_OPTIONAL_TESTS" -eq 1 ]]; then
    export SQ66_HIL_DOA_PLAYBACK=1
    export SQ66_HIL_DOA_SPI_PLAYBACK=1
    if [[ "$RUN_FIRMWARE" == "0" && -z "${SQ66_HIL_XSCOPE_LOG:-}" ]]; then
        export SQ66_HIL_DOA_PLAYBACK=0
        printf 'note=disabled SQ66_HIL_DOA_PLAYBACK because --no-run-firmware was used without SQ66_HIL_XSCOPE_LOG\n'
    fi
else
    export SQ66_HIL_DOA_PLAYBACK=0
    export SQ66_HIL_DOA_SPI_PLAYBACK=0
fi

if [[ -z "$PYTHON_BIN" ]]; then
    if [[ -x ".venv/bin/python" ]]; then
        PYTHON_BIN=".venv/bin/python"
    else
        PYTHON_BIN="python3"
    fi
fi

case "$MODE" in
    full)
        TEST_PATHS=("tests/test_hil" "tests/test_hw_sq66_firmware")
        ;;
    smoke)
        TEST_PATHS=("tests/test_hw_sq66_firmware/test_sq66_hil_smoke.py")
        ;;
    *)
        die "unexpected mode: $MODE"
        ;;
esac

PYTEST_ARGS=(-m pytest "${TEST_PATHS[@]}" -q -rs)
if [[ "$FAIL_FAST" -eq 1 ]]; then
    PYTEST_ARGS+=(-x)
fi
if [[ "${#PYTEST_EXTRA_ARGS[@]}" -gt 0 ]]; then
    PYTEST_ARGS+=("${PYTEST_EXTRA_ARGS[@]}")
fi

printf 'mode=%s\n' "$MODE"
printf 'python_bin=%s\n' "$PYTHON_BIN"
printf 'sq66_rpi_host=%s\n' "$SQ66_RPI_HOST"
printf 'sq66_rpi_cli_cmd=%s\n' "$SQ66_RPI_CLI_CMD"
printf 'sq66_rpi_py_cmd=%s\n' "$SQ66_RPI_PY_CMD"
printf 'sq66_hil_run_firmware=%s\n' "$SQ66_HIL_RUN_FIRMWARE"
printf 'sq66_hil_run_mode=%s\n' "$SQ66_HIL_RUN_MODE"
printf 'fail_fast=%s\n' "$FAIL_FAST"
printf 'require_no_skip=%s\n' "$REQUIRE_NO_SKIP"
printf 'enable_optional_tests=%s\n' "$ENABLE_OPTIONAL_TESTS"

JUNIT_XML="$(mktemp -t sq66_hil_junit_XXXX.xml)"
cleanup() {
    rm -f "$JUNIT_XML"
}
trap cleanup EXIT

PYTEST_ARGS+=(--junitxml "$JUNIT_XML")

if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '+ %s %s\n' "$PYTHON_BIN" "${PYTEST_ARGS[*]}"
    exit 0
fi

set +e
"$PYTHON_BIN" "${PYTEST_ARGS[@]}"
pytest_rc=$?
set -e

if [[ "$pytest_rc" -ne 0 ]]; then
    exit "$pytest_rc"
fi

if [[ "$REQUIRE_NO_SKIP" -eq 1 ]]; then
    skipped_count="$($PYTHON_BIN - <<'PY' "$JUNIT_XML"
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
if root.tag == "testsuite":
    suites = [root]
else:
    suites = root.findall("testsuite")
skipped = 0
for suite in suites:
    skipped += int(suite.attrib.get("skipped", "0"))
print(skipped)
PY
)"
    if [[ "$skipped_count" != "0" ]]; then
        die "run completed with skipped tests (skipped=$skipped_count). Re-run with --allow-skips if intentional."
    fi
fi

printf 'result=pass\n'
