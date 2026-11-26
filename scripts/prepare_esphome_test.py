#!/usr/bin/env python3
"""Create a local overlay on a pinned, unmodified FPH ESPHome source checkout."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ESPHOME_REVISION = "ef0b3d974e686c70bb4556321e1322b750eacc5c"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "build_test/esphome-upstream")
    parser.add_argument("--profile", choices=["calibrated_beam", "diagnostics", "upstream"], default="calibrated_beam")
    args = parser.parse_args()
    source = args.source.resolve()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if revision != ESPHOME_REVISION:
        raise SystemExit(f"Expected FPH ESPHome {ESPHOME_REVISION}, got {revision}")
    if subprocess.check_output(["git", "diff", "--name-only", "HEAD"], cwd=source, text=True).strip():
        raise SystemExit("FPH ESPHome source has tracked changes; use an unmodified checkout")
    artifacts = ROOT / "build_test/artifacts"
    metadata = json.loads((artifacts / "manifest.json").read_text())[args.profile]
    image = artifacts / args.profile / "satellite1_xmos.factory.bin"
    md5 = image.with_suffix(".md5")
    if hashlib.sha256(image.read_bytes()).hexdigest() != metadata["sha256"]:
        raise SystemExit("Packaged XMOS image changed after verification")
    output = source / "config" / f"satellite1.tater-{args.profile}.yaml"
    quote = json.dumps
    output.write_text(f'''# Generated bench overlay; upstream firmware sources remain unchanged.
substitutions:
  node_name: sat1-xmos-bench
  friendly_name: Sat1 XMOS Bench
  esp32_fw_version: tater-xmos-{args.profile}-dev
  xmos_fw_version: {quote(metadata["version"])}

packages:
  fph_firmware: !include satellite1.yaml

memory_flasher:
  - id: !extend xflash
    embed_flash_image:
      image_version: {quote(metadata["version"])}
      image_file:
        type: local
        path: {quote(str(image))}
      md5_file:
        type: local
        path: {quote(str(md5))}
''')
    print(output)


if __name__ == "__main__":
    main()
