import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.conftest import PROJ_ROOT


SCRIPT = PROJ_ROOT / "tools" / "ci" / "package_firmware_deb.sh"
CONTROL_TEMPLATE = PROJ_ROOT / "debian" / "control.in"
DPKG_DEB = shutil.which("dpkg-deb")


@pytest.mark.skipif(DPKG_DEB is None, reason="dpkg-deb is required for Debian package tests")
def test_packages_discovered_images_with_manifest(tmp_path: Path):
    dist = tmp_path / "dist"
    output = tmp_path / "output"
    dist.mkdir()
    factory = dist / "custom-board.factory.bin"
    update = dist / "custom-board.upgrade.bin"
    factory.write_bytes(b"factory bytes\x00")
    update.write_bytes(b"update bytes\x01")
    version_file = tmp_path / "firmware_version.txt"
    version_file.write_text("v1.2.3-alpha.4\n")

    result = subprocess.run(
        [
            "bash", str(SCRIPT), "--dist-dir", str(dist), "--output-dir", str(output),
            "--version-file", str(version_file), "--control-template", str(CONTROL_TEMPLATE),
            "--package-revision", "9",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    package = output / "satellite1-xmos-firmware_1.2.3-alpha.4-9_all.deb"
    assert package.is_file(), result.stdout
    assert subprocess.run([DPKG_DEB, "-f", package, "Package"], capture_output=True, text=True, check=True).stdout.strip() == "satellite1-xmos-firmware"
    assert subprocess.run([DPKG_DEB, "-f", package, "Version"], capture_output=True, text=True, check=True).stdout.strip() == "1.2.3-alpha.4-9"
    assert subprocess.run([DPKG_DEB, "-f", package, "Architecture"], capture_output=True, text=True, check=True).stdout.strip() == "all"
    assert subprocess.run([DPKG_DEB, "-f", package, "Depends"], capture_output=True, text=True, check=True).stdout.strip() == ""

    extracted = tmp_path / "extracted"
    subprocess.run([DPKG_DEB, "-x", package, extracted], check=True)
    payload = extracted / "usr/lib/firmware/satellite1/xmos"
    manifest = json.loads((payload / "manifest.json").read_text())
    assert list(manifest) == [
        "schema_version", "firmware_version", "factory_image",
        "factory_image_sha256", "update_image", "update_image_sha256",
    ]
    assert manifest["schema_version"] == 1
    assert manifest["firmware_version"] == "v1.2.3-alpha.4"
    assert manifest["factory_image"] == factory.name
    assert manifest["update_image"] == update.name
    assert manifest["factory_image_sha256"] == hashlib.sha256(factory.read_bytes()).hexdigest()
    assert manifest["update_image_sha256"] == hashlib.sha256(update.read_bytes()).hexdigest()


def test_rejects_ambiguous_factory_images(tmp_path: Path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "one.factory.bin").write_bytes(b"one")
    (dist / "two.factory.bin").write_bytes(b"two")
    (dist / "one.upgrade.bin").write_bytes(b"update")
    version_file = tmp_path / "firmware_version.txt"
    version_file.write_text("v1.2.3\n")

    result = subprocess.run(
        [
            "bash", str(SCRIPT), "--dist-dir", str(dist), "--output-dir", str(tmp_path / "output"),
            "--version-file", str(version_file), "--control-template", str(CONTROL_TEMPLATE),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "expected exactly one *.factory.bin" in result.stderr


def test_rejects_non_release_version(tmp_path: Path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "board.factory.bin").write_bytes(b"factory")
    (dist / "board.upgrade.bin").write_bytes(b"update")
    version_file = tmp_path / "firmware_version.txt"
    version_file.write_text("dev\n")

    result = subprocess.run(
        [
            "bash", str(SCRIPT), "--dist-dir", str(dist), "--output-dir", str(tmp_path / "output"),
            "--version-file", str(version_file), "--control-template", str(CONTROL_TEMPLATE),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "firmware version must be a release version" in result.stderr
