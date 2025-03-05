#!/bin/bash

# needs a devrule to allow non-root user to access device:
# SUBSYSTEMS=="usb", ATTRS{idVendor}=="20b1", ATTRS{idProduct}=="4000", GROUP="plugdev", MODE="0666"
#
# also, enable authentication via ssh-key

# Check if an argument was provided
if [ $# -ne 1 ]; then
    echo "Usage: $0 <filename>"
    exit 1
fi

# Assign the first argument to a variable
IMAGE="$1"

REMOTE_USER="mischa"
REMOTE_HOST="jetson.local"

# Copy the file to the remote host
scp "$IMAGE" "$REMOTE_USER@$REMOTE_HOST:~/"

# Execute dfu-util on the remote host
ssh "$REMOTE_USER@$REMOTE_HOST" "dfu-util -a 1 -D ~/$IMAGE -R"