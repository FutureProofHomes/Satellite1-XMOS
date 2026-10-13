#!/bin/sh
# Checks, in a built firmware image, that the stack the speaker EQ servicer
# reserves for its read and write callbacks covers them. The callbacks are
# reached through device_control_servicer_cmd_recv()'s function pointers, which
# RTOS_THREAD_STACK_SIZE sizes as device_control_cb_fptr_grp; a callback left
# out of that group overruns the servicer's stack once it needs more than the
# group's largest member.
# Needs the XTC tools on PATH and a built image:
#   make -C build satellite1_firmware_fixed_delay
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../.." && pwd)
BUILD=${BUILD_DIR:-$ROOT/build}
XE=${1:-$BUILD/satellite1_firmware_fixed_delay.xe}
case "$XE" in /*) ;; *) XE=$PWD/$XE ;; esac
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

(cd "$TMP" && xobjdump --split "$XE" > /dev/null)

# words <elf> <symbol prefix>: its stack words, empty if it is not on that tile.
words() {
    v=$(xobjdump -t "$1" | awk -v s="$2.nstackwords" '$NF == s { print $1; exit }')
    if [ -n "$v" ]; then printf '%d' "$v"; fi
}

fail=0
checked=0
for elf in "$TMP"/image_n0c*_2.elf; do
    tile=$(basename "$elf" | sed 's/image_n0c\([0-9]\)_2.elf/tile \1/')
    group=$(words "$elf" _fptrgroup.device_control_cb_fptr_grp)
    for cb in speaker_eq_servicer_read_cmd speaker_eq_servicer_write_cmd; do
        need=$(words "$elf" "$cb")
        if [ -z "$need" ]; then
            continue
        fi
        checked=$((checked + 1))
        if [ -z "$group" ] || [ "$group" -lt "$need" ]; then
            echo "FAIL $tile: $cb needs $need stack words, the servicer reserves ${group:-0} for its callbacks"
            fail=1
        else
            echo "ok   $tile: $cb needs $need stack words, the servicer reserves $group"
        fi
    done
done

if [ "$checked" -eq 0 ]; then
    echo "FAIL: no speaker EQ servicer callbacks in $XE"
    exit 1
fi
exit $fail
