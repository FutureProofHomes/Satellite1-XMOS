"""
HIL (Hardware-In-the-Loop) utilities for Satellite1 testing.

This package contains shared infrastructure code for HIL/e2e tests,
including SSH helpers, audio playback/recording, and other test utilities.
"""

from hil_utils.ssh_helpers import (
    SSHSession,
    CmdResult,
    ProcHandle,
    RemoteAudioSession,
)

__all__ = [
    "SSHSession",
    "CmdResult",
    "ProcHandle",
    "RemoteAudioSession",
]
