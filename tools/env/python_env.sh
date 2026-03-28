#!/usr/bin/env bash

set -euo pipefail

usage()
{
    cat <<'EOF'
Usage: tools/env/python_env.sh [--setup|--check] [--with-tests] [--reinstall]

Manage the repository-local Python virtual environment at .venv.

Modes:
  --setup       Create .venv if missing and install requirements.
  --check       Validate .venv and dependency availability.

Options:
  --with-tests  Include requirements_tests.txt in setup/check.
  --reinstall   Force reinstall of dependencies during --setup.
  -h, --help    Show this help text.

Notes:
  - This script is intended to be executed, not sourced.
  - Dependency installs always use '.venv/bin/python -m pip' to avoid
    accidentally installing into another Python environment.
EOF
}

die()
{
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
    :
else
    script_path="${BASH_SOURCE[0]}"
    if [[ "$script_path" != /* ]]; then
        script_path="$PWD/$script_path"
    fi
    script_dir="$(cd "$(dirname "$script_path")" && pwd)"
    repo_root="$(cd "$script_dir/../.." && pwd)"
fi

venv_dir="$repo_root/.venv"
venv_python="$venv_dir/bin/python"
requirements_file="$repo_root/requirements.txt"
requirements_tests_file="$repo_root/requirements_tests.txt"

mode="setup"
with_tests=0
reinstall=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --setup)
            mode="setup"
            ;;
        --check)
            mode="check"
            ;;
        --with-tests)
            with_tests=1
            ;;
        --reinstall)
            reinstall=1
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

ensure_venv_exists()
{
    if [[ -x "$venv_python" ]]; then
        return 0
    fi

    local creator=""
    if command -v python3.10 >/dev/null 2>&1; then
        creator="python3.10"
    elif command -v python3 >/dev/null 2>&1; then
        creator="python3"
    else
        die "python3.10/python3 not found; install Python before creating .venv"
    fi

    printf 'Creating virtual environment at %s using %s\n' "$venv_dir" "$creator"
    "$creator" -m venv "$venv_dir"
}

install_requirements()
{
    local req="$1"
    if [[ ! -f "$req" ]]; then
        die "requirements file not found: $req"
    fi

    if [[ "$reinstall" -eq 1 ]]; then
        "$venv_python" -m pip install --upgrade --force-reinstall -r "$req"
    else
        "$venv_python" -m pip install -r "$req"
    fi
}

show_python_paths()
{
    local active_python=""
    active_python="$(python -c 'import sys; print(sys.executable)' 2>/dev/null || true)"
    if [[ -n "$active_python" ]]; then
        printf 'shell_python=%s\n' "$active_python"
    else
        printf 'shell_python=unavailable\n'
    fi
    printf 'venv_python=%s\n' "$venv_python"
}

check_packages()
{
    "$venv_python" -m pip --version >/dev/null
    "$venv_python" -m pip install -r "$requirements_file" --dry-run >/dev/null
    if [[ "$with_tests" -eq 1 ]]; then
        "$venv_python" -m pip install -r "$requirements_tests_file" --dry-run >/dev/null
    fi
}

if [[ "$mode" == "setup" ]]; then
    ensure_venv_exists
    install_requirements "$requirements_file"
    if [[ "$with_tests" -eq 1 ]]; then
        install_requirements "$requirements_tests_file"
    fi
    show_python_paths
    printf 'Setup complete. Activate with: source .venv/bin/activate\n'
    exit 0
fi

if [[ ! -x "$venv_python" ]]; then
    die "missing $venv_python; run: tools/env/python_env.sh --setup"
fi

check_packages
show_python_paths

printf 'python virtual environment check passed\n'
exit 0
