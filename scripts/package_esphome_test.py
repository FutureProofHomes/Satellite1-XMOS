#!/usr/bin/env python3
"""Preserve a verified FPH ESPHome host image before building another profile."""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from prepare_esphome_test import ESPHOME_REVISION, ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "build_test/esphome-upstream")
    parser.add_argument("--profile", choices=["calibrated_beam", "diagnostics", "upstream"], required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if revision != ESPHOME_REVISION or subprocess.check_output(
            ["git", "diff", "--name-only", "HEAD"], cwd=source, text=True).strip():
        raise SystemExit("Use the pinned, unmodified FPH ESPHome checkout")
    artifacts = ROOT / "build_test/artifacts"
    manifest_path = artifacts / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    metadata = manifest[args.profile]
    destination = artifacts / args.profile
    xmos = (destination / "satellite1_xmos.factory.bin").read_bytes()
    if hashlib.sha256(xmos).hexdigest() != metadata["sha256"]:
        raise SystemExit("Packaged XMOS image changed after verification")
    build = source / "config/.esphome/build/sat1-xmos-bench/build"
    images = {}
    # Validate both before copying either. The raw embedded XMOS array must
    # survive linking verbatim; this also detects a stale comparison build.
    for kind in ("factory", "ota"):
        data = (build / f"firmware.{kind}.bin").read_bytes()
        if data.count(xmos) != 1:
            raise SystemExit(f"ESPHome {kind} image does not embed the expected XMOS image exactly once")
        images[kind] = data
    host = {"source_commit": revision, "esphome": "2026.10.2", "images": {}}
    for kind, data in images.items():
        name = f"fph-esphome.{kind}.bin"
        shutil.copyfile(build / f"firmware.{kind}.bin", destination / name)
        host["images"][kind] = {
            "file": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        }
        print(f"{args.profile}: {name}, {len(data)} bytes, SHA256 {host['images'][kind]['sha256']}")
    metadata["fph_esphome"] = host
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
