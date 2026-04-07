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
SAT1_RPI_HOST_ARG="${SAT1_RPI_HOST:-}"
SAT1_RPI_CLI_CMD_ARG="${SAT1_RPI_CLI_CMD:-sat1}"
SAT1_RPI_PY_CMD_ARG="${SAT1_RPI_PY_CMD:-/opt/satellite1/venv/bin/python}"
PYTHON_BIN=""
PYTEST_EXTRA_ARGS=()

usage() {
    cat <<'EOF'
Usage: tools/e2e/run_sat1_hil_e2e.sh [options] [-- <extra pytest args>]

Run Satellite1 HIL pytest suites with fail-fast and skip policy controls.

Modes (default: --full):
  --full                Run full SAT1 HIL suite in tests/test_hil and tests/test_hil_sat1.
  --smoke               Run only SAT1 smoke test file.

Behavior options:
  --allow-skips         Do not fail run when tests are skipped.
  --no-fail-fast        Disable pytest fail-fast (-x).
  --disable-optional    Do not auto-enable optional pattern/playback env gates.
  --python-bin PATH     Python executable for pytest (default: .venv/bin/python if present, else python3).
  --dry-run             Print commands without executing them.

Remote target options:
  --rpi-host HOST       Override SAT1_RPI_HOST.
  --sat1-cmd CMD        Override SAT1_RPI_CLI_CMD.
  --sat1-py-cmd CMD     Override SAT1_RPI_PY_CMD.

Examples:
  tools/e2e/run_sat1_hil_e2e.sh --full
  tools/e2e/run_sat1_hil_e2e.sh --smoke
  tools/e2e/run_sat1_hil_e2e.sh --full --allow-skips
  tools/e2e/run_sat1_hil_e2e.sh --full -- --maxfail=1 -k doa
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
        --python-bin)
            shift
            [[ $# -gt 0 ]] || die "--python-bin requires a value"
            PYTHON_BIN="$1"
            ;;
        --rpi-host)
            shift
            [[ $# -gt 0 ]] || die "--rpi-host requires a value"
            SAT1_RPI_HOST_ARG="$1"
            ;;
        --sat1-cmd)
            shift
            [[ $# -gt 0 ]] || die "--sat1-cmd requires a value"
            SAT1_RPI_CLI_CMD_ARG="$1"
            ;;
        --sat1-py-cmd)
            shift
            [[ $# -gt 0 ]] || die "--sat1-py-cmd requires a value"
            SAT1_RPI_PY_CMD_ARG="$1"
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

cd "$REPO_ROOT"
[[ -f "$XMOS_ENV_WRAPPER" ]] || die "XMOS env wrapper not found: $XMOS_ENV_WRAPPER"

set +u
# shellcheck disable=SC1090
source "$XMOS_ENV_WRAPPER"
set -u

if [[ -z "${SAT1_RPI_HOST_ARG:-}" && -f "$REPO_ROOT/.env" ]]; then
    set +u
    # shellcheck disable=SC1090
    source "$REPO_ROOT/.env"
    set -u
    SAT1_RPI_HOST_ARG="${SAT1_RPI_HOST:-}"
    SAT1_RPI_CLI_CMD_ARG="${SAT1_RPI_CLI_CMD:-$SAT1_RPI_CLI_CMD_ARG}"
    SAT1_RPI_PY_CMD_ARG="${SAT1_RPI_PY_CMD:-$SAT1_RPI_PY_CMD_ARG}"
fi

if [[ -z "${SAT1_RPI_HOST_ARG:-}" ]]; then
    die "--rpi-host (or SAT1_RPI_HOST via xmos_env/.env) is required"
fi

export SAT1_HIL=1
export SAT1_RPI_HOST="$SAT1_RPI_HOST_ARG"
export SAT1_RPI_CLI_CMD="$SAT1_RPI_CLI_CMD_ARG"
export SAT1_RPI_PY_CMD="$SAT1_RPI_PY_CMD_ARG"

if [[ "$ENABLE_OPTIONAL_TESTS" -eq 1 ]]; then
    export SAT1_HIL_MIC_PATTERN_TEST=1
    export SAT1_HIL_SPK_PATTERN_TEST=1
    export SAT1_HIL_WAV_PATTERN_TEST=1
    export SAT1_HIL_DOA_PLAYBACK=1
    if [[ -z "${SAT1_HIL_SPI_CONSISTENCY_ITERS:-}" || "${SAT1_HIL_SPI_CONSISTENCY_ITERS}" -lt 2 ]]; then
        export SAT1_HIL_SPI_CONSISTENCY_ITERS=3
    fi
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
        TEST_PATHS=("tests/test_hil" "tests/test_hil_sat1")
        ;;
    smoke)
        TEST_PATHS=("tests/test_hil_sat1/test_sat1_hil_smoke.py")
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
printf 'sat1_rpi_host=%s\n' "$SAT1_RPI_HOST"
printf 'sat1_rpi_cli_cmd=%s\n' "$SAT1_RPI_CLI_CMD"
printf 'sat1_rpi_py_cmd=%s\n' "$SAT1_RPI_PY_CMD"
printf 'fail_fast=%s\n' "$FAIL_FAST"
printf 'require_no_skip=%s\n' "$REQUIRE_NO_SKIP"
printf 'enable_optional_tests=%s\n' "$ENABLE_OPTIONAL_TESTS"

JUNIT_XML="$(mktemp -t sat1_hil_junit_XXXX.xml)"
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
