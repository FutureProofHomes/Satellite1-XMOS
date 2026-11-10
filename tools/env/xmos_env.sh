#!/usr/bin/env bash

if XMOS_ENV_REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
    :
else
    XMOS_ENV_SCRIPT_PATH="${BASH_SOURCE[0]}"
    if [[ "$XMOS_ENV_SCRIPT_PATH" != /* ]]; then
        XMOS_ENV_SCRIPT_PATH="$PWD/$XMOS_ENV_SCRIPT_PATH"
    fi
    XMOS_ENV_SCRIPT_DIR="$(cd "$(dirname "$XMOS_ENV_SCRIPT_PATH")" && pwd)"
    XMOS_ENV_REPO_ROOT="$(cd "$XMOS_ENV_SCRIPT_DIR/../.." && pwd)"
fi

DOTENV_PATH="$XMOS_ENV_REPO_ROOT/.env"

if [[ -n "${BASH_VERSION:-}" ]]; then
    set -euo pipefail
fi

if [[ -f "$DOTENV_PATH" ]]; then
    set +u
    set -a
    # shellcheck disable=SC1090
    source "$DOTENV_PATH"
    set +a
    set -u
fi

XMOS_XTC_ROOT="${XMOS_XTC_ROOT:-$HOME/Projects/FutureProofHomes/XMOS_XTC_15.3.1}"
export XMOS_XTC_ROOT
XMOS_ENV_SCRIPT="$XMOS_XTC_ROOT/SetEnv.sh"
XMOS_BIN_DIR="$XMOS_XTC_ROOT/bin"

if [[ ! -f "$XMOS_ENV_SCRIPT" ]]; then
    printf 'error: XMOS env script not found: %s\n' "$XMOS_ENV_SCRIPT" >&2
    printf 'set XMOS_XTC_ROOT to your local XMOS toolchain directory\n' >&2
    return 1 2>/dev/null || exit 1
fi

set +u
# shellcheck disable=SC1090
source "$XMOS_ENV_SCRIPT"
set -u

if [[ -d "$XMOS_BIN_DIR" ]]; then
    export PATH="$XMOS_BIN_DIR:$PATH"
fi
