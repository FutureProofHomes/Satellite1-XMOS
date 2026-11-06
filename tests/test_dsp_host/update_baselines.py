#!/usr/bin/env python3
"""Regenerate DSP baselines after an intentional pipeline change.

Usage:
    source .venv-dsp/bin/activate
    python tests/test_dsp_host/update_baselines.py [--binary /path/to/binary]

Workflow:
    1. Make intentional DSP change
    2. Run this script
    3. Review generated baselines (listen, check metrics)
    4. git add tests/test_dsp_host/baselines/ && git commit -m "Update DSP baselines: <reason>"
"""
import argparse
import subprocess
import sys
from pathlib import Path

TEST_DIR = Path(__file__).parent
STIMULI_DIR = TEST_DIR / "stimuli"
BASELINE_DIR = TEST_DIR / "baselines"
DEFAULT_BINARY = TEST_DIR / "build" / "dsp_pipeline_test"


def main():
    parser = argparse.ArgumentParser(description="Regenerate DSP baselines")
    parser.add_argument("--binary", type=str, default=None, help="Path to pipeline binary")
    args = parser.parse_args()

    binary = Path(args.binary) if args.binary else DEFAULT_BINARY
    if not binary.exists():
        print(f"Error: binary not found at {binary}")
        print("Build with: bash tools/build_dsp_host.sh")
        sys.exit(1)

    BASELINE_DIR.mkdir(exist_ok=True)
    stimuli = sorted(STIMULI_DIR.glob("*.wav"))
    if not stimuli:
        print("Error: no stimuli found. Run generate_stimuli.py first.")
        sys.exit(1)

    print(f"Using binary: {binary}")
    print(f"Generating {len(stimuli)} baselines...")
    print()

    for stim in stimuli:
        out_path = BASELINE_DIR / f"{stim.stem}_baseline.wav"
        print(f"  {stim.name} -> {out_path.name}", end=" ")
        result = subprocess.run(
            [str(binary), str(stim), str(out_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"FAILED (rc={result.returncode})")
            print(f"    stderr: {result.stderr}")
        else:
            size_mb = out_path.stat().st_size / 1e6
            print(f"OK ({size_mb:.1f} MB)")

    print()
    print(f"Done. {len(stimuli)} baselines written to {BASELINE_DIR}/")
    print("Review them, then commit:")
    print(f"  git add {BASELINE_DIR.relative_to(Path.cwd().parent)}/")
    print('  git commit -m "Update DSP baselines: <reason>"')


if __name__ == "__main__":
    main()
