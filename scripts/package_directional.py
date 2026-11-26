#!/usr/bin/env python3
"""Verify linked test identities and package factory images for ESPHome tests."""
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {"calibrated_beam": ("calibrated_beam", 17), "diagnostics": ("fixed_delay", 18), "upstream": ("fixed_delay", 19), "speech_tracking": ("speech_tracking", 16)}

def linked_versions(executable):
    """Read the DFU identity from linked ELF symbols, not the shared source header."""
    tool = Path(shutil.which("xobjdump") or "/Applications/XMOS_XTC_15.3.1/bin/xobjdump")
    versions = set()
    with tempfile.TemporaryDirectory() as temporary:
        subprocess.run([str(tool), "--split", "--split-dir", temporary, str(executable)],
                       check=True, capture_output=True)
        for path in Path(temporary).rglob("*"):
            if not path.is_file():
                continue
            data = path.read_bytes()
            if data[:6] != b"\x7fELF\x01\x01":
                continue
            offset = struct.unpack_from("<I", data, 32)[0]
            stride, count = struct.unpack_from("<HH", data, 46)
            sections = [struct.unpack_from("<10I", data, offset + i * stride)
                        for i in range(count)]
            for section in sections:
                if section[1] != 2:  # ELF32 SHT_SYMTAB
                    continue
                strings = sections[section[6]]
                names = data[strings[4]:strings[4] + strings[5]]
                for position in range(section[4], section[4] + section[5], section[9]):
                    name, address, size, _, _, index = struct.unpack_from("<IIIBBH", data, position)
                    if names[name:].split(b"\0", 1)[0] != b"dfu_servicer_read_cmd.version":
                        continue
                    assert size == 5 and index < len(sections)
                    containing = sections[index]
                    start = containing[4] + address - containing[3]
                    versions.add(tuple(data[start:start + size]))
    return versions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profiles", nargs="+", choices=PROFILES)
    args = parser.parse_args()
    destination = ROOT / "build_test/artifacts"
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    for profile in args.profiles:
        target, counter = PROFILES[profile]
        build = ROOT / f"build_{profile}"
        name = f"satellite1_firmware_{target}"
        expected = (1, 2, 0, 4, counter)
        if linked_versions(build / f"tile0_{name}.xe") != {expected}:
            raise SystemExit(f"Unexpected linked version for {profile}")
        image = (build / f"{name}.factory.bin").read_bytes()
        digest = hashlib.md5(image).hexdigest()
        if (build / f"{name}.factory.md5").read_text().strip().split()[0] != digest:
            raise SystemExit(f"Factory checksum mismatch for {profile}")
        output = destination / profile
        output.mkdir(exist_ok=True)
        (output / "satellite1_xmos.factory.bin").write_bytes(image)
        (output / "satellite1_xmos.factory.md5").write_text(digest + "\n")
        manifest[profile] = {
            "version": f"v1.2.0-dev.{counter}", "linked_version": list(expected),
            "target": name, "bytes": len(image), "md5": digest,
            "sha256": hashlib.sha256(image).hexdigest(), "source_commit": revision,
            "source_dirty": dirty, "upstream_base": "ace8050265f134c1e0442661c8a16866467c9e53",
            "fwk_voice": "74b9e2e2c4b747efe124f35a52e654e0a19b6c87",
            "protocol": "0x11", "doa_resource": 233 if profile != "upstream" else None,
            "ic_vnr_stage_bypassed": profile not in ("calibrated_beam", "speech_tracking"),
            "host_hints": profile == "speech_tracking",
            "reference_channels": 1 if profile in ("speech_tracking", "upstream", "diagnostics") else 2,
            "hardware_validation": "pending",
        }
        print(f"{profile}: {len(image)} bytes, {manifest[profile]['version']}, SHA256 {manifest[profile]['sha256']}")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
