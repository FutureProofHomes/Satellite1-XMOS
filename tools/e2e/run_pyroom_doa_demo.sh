#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

HOST="${SAT1_RPI_HOST:-}"
PY_CMD="${SAT1_RPI_PY_CMD:-/opt/satellite1/venv/bin/python}"
ANGLES_DEG="30,90,150,-90"
SEGMENT_S="3"
POLL_S="0.1"
APLAY_DEV="hw:0,0"
REMOTE_WAV="/tmp/doa_pyroom_set.wav"
REMOTE_WAV_USER_SET=0
PLOT_SOURCE="python"
MIC_MAP="4,5,0,1"
KEEP_FILES=0
EFFECTIVE_MIC_MAP=""
PLAYBACK_PID=""
EXPECTED_OFFSET_DEG="0"
SDK_RETRY_ATTEMPTS="${SAT1_DOA_DEMO_SDK_RETRY_ATTEMPTS:-8}"
SDK_RETRY_DELAY_S="${SAT1_DOA_DEMO_SDK_RETRY_DELAY_S:-0.4}"
ORIG_MIC_SOURCE_MODE=""
ORIG_MIC_MAP=""

usage() {
    cat <<'EOF'
Usage: tools/e2e/run_pyroom_doa_demo.sh [options]

Generate a pyroomacoustics DoA test set, play it on the Pi, and open the
live DoA plot with expected-angle overlay.

Angle convention:
  --angles-deg uses firmware DoA convention (arrival direction).
  The generator places pyroom sources at the opposite bearing automatically.

Options:
  --host HOST          SSH host (default: SAT1_RPI_HOST)
  --py-cmd CMD         Remote python command (default: SAT1_RPI_PY_CMD or /opt/satellite1/venv/bin/python)
  --angles-deg CSV     Segment angles in degrees (default: 30,90,150,-90)
  --segment-s SEC      Seconds per segment (default: 3)
  --poll-s SEC         Plot polling period (default: 0.1)
  --aplay-dev DEV      Remote ALSA playback device (default: hw:0,0)
  --remote-wav PATH    Remote WAV path on host (default: /tmp/doa_pyroom_set.wav)
  --source MODE        Plot source mode: python|stream|cli (default: python)
  --mic-map CSV        Mic map (default: 4,5,0,1)
  --expected-offset-deg N  Expected-angle offset for plot overlay (default: 0)
  --keep-files         Keep generated local temp files
  -h, --help           Show this help

Prerequisites:
  - Local: python3 with numpy + pyroomacoustics + matplotlib
  - Remote: sat1 SDK installed and working XMOS SPI DoA commands
EOF
}

cleanup() {
    if [[ -z "$HOST" ]]; then
        return
    fi

    if [[ -n "$ORIG_MIC_SOURCE_MODE" && -n "$ORIG_MIC_MAP" ]]; then
        RESTORE_SCRIPT="from satellite1.sat1_hat import XMOS; x=XMOS(); x.setup(); _=x.read_firmware(); _=x.wait_until_ready(timeout_s=3.0,poll_interval_s=0.1); _=x.set_mic_input_channel_maps(mic_input_channel_map=[int(v) for v in '$ORIG_MIC_MAP'.split(',') if v.strip()]); _=x.set_mic_input_source_modes(mic_source_mode=int('$ORIG_MIC_SOURCE_MODE')); c=getattr(x,'_cntrl',None); c.close() if c is not None and hasattr(c,'close') else None"
        remote_python_retry "$RESTORE_SCRIPT" >/dev/null 2>&1 || true
    fi

    if [[ -n "$PLAYBACK_PID" ]]; then
        ssh -o BatchMode=yes -o ConnectTimeout=5 "$HOST" "kill $PLAYBACK_PID >/dev/null 2>&1 || true" || true
    fi
    ssh -o BatchMode=yes -o ConnectTimeout=5 "$HOST" "pkill -f 'aplay -D $APLAY_DEV -f S32_LE -r 48000 -c 2 /tmp/doa_pyroom_set_' >/dev/null 2>&1 || true" || true
    ssh -o BatchMode=yes -o ConnectTimeout=5 "$HOST" "pkill -f sat1_doa_stream_marker_v1 >/dev/null 2>&1 || true" || true
}

trap cleanup EXIT

remote_python_retry() {
    local script="$1"
    local attempt=1
    local out=""

    while [[ "$attempt" -le "$SDK_RETRY_ATTEMPTS" ]]; do
        if out="$(ssh -o BatchMode=yes -o ConnectTimeout=5 "$HOST" "$PY_CMD -c \"$script\"" 2>/dev/null)"; then
            if [[ -n "${out//[[:space:]]/}" ]]; then
                printf '%s\n' "$out"
                return 0
            fi
        fi
        sleep "$SDK_RETRY_DELAY_S"
        attempt=$((attempt + 1))
    done

    return 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            shift
            HOST="${1:-}"
            ;;
        --py-cmd)
            shift
            PY_CMD="${1:-}"
            ;;
        --angles-deg)
            shift
            ANGLES_DEG="${1:-}"
            ;;
        --segment-s)
            shift
            SEGMENT_S="${1:-}"
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
            REMOTE_WAV_USER_SET=1
            ;;
        --source)
            shift
            PLOT_SOURCE="${1:-}"
            ;;
        --mic-map)
            shift
            MIC_MAP="${1:-}"
            ;;
        --keep-files)
            KEEP_FILES=1
            ;;
        --expected-offset-deg)
            shift
            EXPECTED_OFFSET_DEG="${1:-}"
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

if [[ -z "$HOST" ]]; then
    printf 'error: --host is required (or set SAT1_RPI_HOST)\n' >&2
    exit 2
fi

if [[ "$PLOT_SOURCE" != "python" && "$PLOT_SOURCE" != "stream" && "$PLOT_SOURCE" != "cli" ]]; then
    printf 'error: --source must be one of: python, stream, cli\n' >&2
    exit 2
fi

if [[ "$MIC_MAP" == "auto" ]]; then
    MIC_MAP_QUERY_SCRIPT="import json; from satellite1.sat1_hat import XMOS; x=XMOS(); x.setup(); _=x.read_firmware(); _=x.wait_until_ready(timeout_s=3.0,poll_interval_s=0.1); s=x.get_mic_input_settings(); print(','.join(str(int(v)) for v in s.mic_input_channel_map)); c=getattr(x,'_cntrl',None); c.close() if c is not None and hasattr(c,'close') else None"
    if ! EFFECTIVE_MIC_MAP="$(remote_python_retry "$MIC_MAP_QUERY_SCRIPT" | tr -d '[:space:]')"; then
        printf 'error: failed to read mic input channel map after %s attempts\n' "$SDK_RETRY_ATTEMPTS" >&2
        printf 'hint: ensure no other long-lived SPI readers are active and device is responsive\n' >&2
        ssh -o BatchMode=yes -o ConnectTimeout=5 "$HOST" "sat1 xmos read-status || true" || true
        exit 2
    fi
else
    EFFECTIVE_MIC_MAP="$MIC_MAP"
fi

if [[ -z "$EFFECTIVE_MIC_MAP" ]]; then
    printf 'error: unable to resolve effective mic map\n' >&2
    exit 2
fi

ORIG_QUERY_SCRIPT="import json; from satellite1.sat1_hat import XMOS; x=XMOS(); x.setup(); _=x.read_firmware(); _=x.wait_until_ready(timeout_s=3.0,poll_interval_s=0.1); s=x.get_mic_input_settings(); print(json.dumps({'mic_source_mode': int(s.mic_source_mode), 'mic_input_channel_map': [int(v) for v in s.mic_input_channel_map]})); c=getattr(x,'_cntrl',None); c.close() if c is not None and hasattr(c,'close') else None"
if ORIG_OUT="$(remote_python_retry "$ORIG_QUERY_SCRIPT")"; then
    ORIG_MIC_SOURCE_MODE="$(printf '%s' "$ORIG_OUT" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read().splitlines()[-1]); print(int(d["mic_source_mode"]))')"
    ORIG_MIC_MAP="$(printf '%s' "$ORIG_OUT" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read().splitlines()[-1]); print(",".join(str(int(v)) for v in d["mic_input_channel_map"]))')"
fi

if [[ ! -f "$REPO_ROOT/tools/e2e/generate_pyroom_doa_set.py" ]]; then
    printf 'error: generator script not found\n' >&2
    exit 2
fi

if [[ ! -f "$REPO_ROOT/tools/e2e/plot_doa_over_ssh.py" ]]; then
    printf 'error: plot script not found\n' >&2
    exit 2
fi

RUN_ID="$(date +%Y%m%d_%H%M%S)"
LOCAL_WAV="/tmp/doa_pyroom_set_${RUN_ID}.wav"
LOCAL_EXPECTED="/tmp/doa_pyroom_set_${RUN_ID}.expected.json"
if [[ "$REMOTE_WAV_USER_SET" -eq 0 ]]; then
    REMOTE_WAV="/tmp/doa_pyroom_set_${RUN_ID}.wav"
fi

printf 'Generating pyroom DoA set...\n'
GEN_ARGS=(
    --host "$HOST"
    --py-cmd "$PY_CMD"
    --angles-deg "$ANGLES_DEG"
    --segment-s "$SEGMENT_S"
    --out-wav "$LOCAL_WAV"
    --out-expected "$LOCAL_EXPECTED"
    --mic-map "$EFFECTIVE_MIC_MAP"
)

python3 "$REPO_ROOT/tools/e2e/generate_pyroom_doa_set.py" "${GEN_ARGS[@]}"

printf 'Setting mic injection routing (mic_source_mode=1, map=%s)...\n' "$EFFECTIVE_MIC_MAP"
ROUTING_SCRIPT="import json; from satellite1.sat1_hat import XMOS; x=XMOS(); x.setup(); _=x.read_firmware(); _=x.wait_until_ready(timeout_s=3.0,poll_interval_s=0.1); vals=[int(v) for v in '$EFFECTIVE_MIC_MAP'.split(',') if v.strip()]; ok1=x.set_mic_input_channel_maps(mic_input_channel_map=vals); ok2=x.set_mic_input_source_modes(mic_source_mode=1); s=x.get_mic_input_settings(); print(json.dumps({'ok': bool(ok1 and ok2), 'mic_source_mode': int(s.mic_source_mode), 'mic_input_channel_map': [int(v) for v in s.mic_input_channel_map]})); c=getattr(x,'_cntrl',None); c.close() if c is not None and hasattr(c,'close') else None"
if ! ROUTING_OUT="$(remote_python_retry "$ROUTING_SCRIPT")"; then
    printf 'error: failed to set/verify mic injection routing after %s attempts\n' "$SDK_RETRY_ATTEMPTS" >&2
    printf 'hint: ensure no competing SPI clients (another plot/session) are running\n' >&2
    ssh -o BatchMode=yes -o ConnectTimeout=5 "$HOST" "sat1 xmos read-status || true" || true
    exit 2
fi
printf 'Routing result: %s\n' "$ROUTING_OUT"
if ! printf '%s' "$ROUTING_OUT" | grep -q '"ok": true'; then
    printf 'error: failed to set mic injection routing on host\n' >&2
    exit 2
fi

printf 'Uploading WAV to %s:%s ...\n' "$HOST" "$REMOTE_WAV"
scp "$LOCAL_WAV" "$HOST:$REMOTE_WAV"

printf 'Starting remote playback...\n'
ssh -o BatchMode=yes -o ConnectTimeout=5 "$HOST" \
    "pkill -f 'aplay -D $APLAY_DEV -f S32_LE -r 48000 -c 2 /tmp/doa_pyroom_set_' >/dev/null 2>&1 || true" || true
PLAYBACK_PID="$(ssh -o BatchMode=yes -o ConnectTimeout=5 "$HOST" "nohup bash -c 'while true; do aplay -D $APLAY_DEV -f S32_LE -r 48000 -c 2 $REMOTE_WAV >/tmp/doa_pyroom_aplay.log 2>&1; done' >/tmp/doa_pyroom_loop.log 2>&1 & echo \$!")"
printf 'Remote playback loop started (pid=%s).\n' "${PLAYBACK_PID:-unknown}"
PLAYBACK_MATCHES="$(ssh -o BatchMode=yes -o ConnectTimeout=5 "$HOST" "pgrep -af '^aplay -D $APLAY_DEV -f S32_LE -r 48000 -c 2 $REMOTE_WAV$' || true")"
if [[ -z "$PLAYBACK_MATCHES" ]]; then
    printf 'error: playback loop started but no active aplay child detected yet.\n' >&2
    printf 'hint: verify --aplay-dev and remote ALSA device availability\n' >&2
    exit 2
else
    printf 'Active playback: %s\n' "$PLAYBACK_MATCHES"
fi

printf 'Launching live DoA plot...\n'
if [[ "${MPLBACKEND:-}" == "Agg" ]]; then
    printf 'warning: MPLBACKEND=Agg disables GUI windows; unsetting for live plot\n'
    unset MPLBACKEND
fi

PLOT_BACKEND="$(python3 -c 'import matplotlib; print(matplotlib.get_backend())' 2>/dev/null || true)"
if [[ "$PLOT_BACKEND" == "agg" || "$PLOT_BACKEND" == "Agg" ]]; then
    printf 'warning: matplotlib backend is %s (non-interactive); plot window may not open\n' "$PLOT_BACKEND"
    printf 'hint: try `python3 -c "import matplotlib; print(matplotlib.get_backend())"` and configure an interactive backend\n'
fi

set +e
python3 "$REPO_ROOT/tools/e2e/plot_doa_over_ssh.py" \
    --host "$HOST" \
    --source "$PLOT_SOURCE" \
    --py-cmd "$PY_CMD" \
    --poll-s "$POLL_S" \
    --expected-file "$LOCAL_EXPECTED" \
    --expected-loop \
    --expected-offset-deg "$EXPECTED_OFFSET_DEG"
PLOT_RC=$?
set -e
if [[ "$PLOT_RC" -ne 0 ]]; then
    printf 'error: plot script exited with code %d\n' "$PLOT_RC" >&2
    exit "$PLOT_RC"
fi

if [[ "$KEEP_FILES" -eq 0 ]]; then
    rm -f "$LOCAL_WAV" "$LOCAL_EXPECTED"
fi
