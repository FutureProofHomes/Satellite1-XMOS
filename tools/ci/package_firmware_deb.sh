#!/usr/bin/env bash
# Build a payload-only Debian package from the firmware images already in dist/.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
dist_dir="$repo_root/dist"
output_dir="$dist_dir"
version_file="$repo_root/firmware_version.txt"
control_template="$repo_root/debian/control.in"
package_revision="${PACKAGE_REVISION:-1}"

usage() {
    cat <<'EOF'
Usage: package_firmware_deb.sh [options]

Build satellite1-xmos-firmware from one *.factory.bin and one *.upgrade.bin in
the distribution directory. PACKAGE_REVISION defaults to 1.

Options:
  --dist-dir DIR          Directory containing firmware images (default: dist/)
  --output-dir DIR        Directory for the resulting .deb (default: dist/)
  --version-file FILE     Firmware version source (default: firmware_version.txt)
  --control-template FILE Debian control template (default: debian/control.in)
  --package-revision REV  Debian packaging revision (default: PACKAGE_REVISION or 1)
EOF
}

while (($#)); do
    case "$1" in
        --dist-dir) dist_dir="$2"; shift 2 ;;
        --output-dir) output_dir="$2"; shift 2 ;;
        --version-file) version_file="$2"; shift 2 ;;
        --control-template) control_template="$2"; shift 2 ;;
        --package-revision) package_revision="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

for required in "$dist_dir" "$version_file" "$control_template"; do
    if [[ ! -e "$required" ]]; then
        echo "ERROR: required path does not exist: $required" >&2
        exit 1
    fi
done

firmware_version=$(python3 - "$version_file" <<'PY'
from pathlib import Path
import sys

lines = Path(sys.argv[1]).read_text().splitlines()
if len(lines) != 1 or not lines[0]:
    raise SystemExit("ERROR: firmware version must contain exactly one non-empty line")
print(lines[0])
PY
)
debian_upstream_version=${firmware_version#v}
if [[ ! "$debian_upstream_version" =~ ^[0-9] ]]; then
    echo "ERROR: firmware version must be a release version beginning with an optional v followed by a digit" >&2
    exit 1
fi
if [[ ! "$package_revision" =~ ^[A-Za-z0-9.+~]+$ ]]; then
    echo "ERROR: invalid Debian packaging revision: $package_revision" >&2
    exit 1
fi
package_version="${debian_upstream_version}-${package_revision}"

shopt -s nullglob
factory_images=("$dist_dir"/*.factory.bin)
update_images=("$dist_dir"/*.upgrade.bin)
shopt -u nullglob
if ((${#factory_images[@]} != 1)); then
    echo "ERROR: expected exactly one *.factory.bin in $dist_dir; found ${#factory_images[@]}" >&2
    exit 1
fi
if ((${#update_images[@]} != 1)); then
    echo "ERROR: expected exactly one *.upgrade.bin in $dist_dir; found ${#update_images[@]}" >&2
    exit 1
fi
for image in "${factory_images[0]}" "${update_images[0]}"; do
    if [[ ! -f "$image" ]]; then
        echo "ERROR: firmware image is not a regular file: $image" >&2
        exit 1
    fi
done

stage_dir=$(mktemp -d "${TMPDIR:-/tmp}/satellite1-xmos-firmware.XXXXXX")
cleanup() { rm -rf "$stage_dir"; }
trap cleanup EXIT
payload_dir="$stage_dir/usr/lib/firmware/satellite1/xmos"
mkdir -p "$stage_dir/DEBIAN" "$payload_dir" "$output_dir"

factory_name=$(basename "${factory_images[0]}")
update_name=$(basename "${update_images[0]}")
cp "${factory_images[0]}" "$payload_dir/$factory_name"
cp "${update_images[0]}" "$payload_dir/$update_name"

python3 - "$control_template" "$stage_dir/DEBIAN/control" "$package_version" <<'PY'
from pathlib import Path
import sys

template = Path(sys.argv[1])
output = Path(sys.argv[2])
package_version = sys.argv[3]
control = template.read_text()
if control.count("@PACKAGE_VERSION@") != 1:
    raise SystemExit("control template must contain exactly one @PACKAGE_VERSION@ placeholder")
Path(output).write_text(control.replace("@PACKAGE_VERSION@", package_version))
PY

manifest="$payload_dir/manifest.json"
python3 - "$manifest" "$firmware_version" "$payload_dir/$factory_name" "$payload_dir/$update_name" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

manifest, firmware_version, factory, update = sys.argv[1:]
def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

payload = {
    "schema_version": 1,
    "firmware_version": firmware_version,
    "factory_image": Path(factory).name,
    "factory_image_sha256": sha256(factory),
    "update_image": Path(update).name,
    "update_image_sha256": sha256(update),
}
Path(manifest).write_text(json.dumps(payload, indent=2) + "\n")
PY

package_path="$output_dir/satellite1-xmos-firmware_${package_version}_all.deb"
dpkg-deb --build --root-owner-group "$stage_dir" "$package_path" >/dev/null

dpkg-deb --info "$package_path" >/dev/null
[[ $(dpkg-deb --field "$package_path" Package) == "satellite1-xmos-firmware" ]]
[[ $(dpkg-deb --field "$package_path" Version) == "$package_version" ]]
[[ $(dpkg-deb --field "$package_path" Architecture) == "all" ]]
[[ -z $(dpkg-deb --field "$package_path" Depends) ]]
contents=$(dpkg-deb --contents "$package_path")
for path in "$factory_name" "$update_name" manifest.json; do
    [[ "$contents" == *"./usr/lib/firmware/satellite1/xmos/$path"* ]] || {
        echo "ERROR: package is missing payload path: $path" >&2
        exit 1
    }
done

extract_dir="$stage_dir/extract"
dpkg-deb --extract "$package_path" "$extract_dir"
python3 - "$extract_dir/usr/lib/firmware/satellite1/xmos/manifest.json" "$firmware_version" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

manifest_path = Path(sys.argv[1])
firmware_version = sys.argv[2]
manifest = json.loads(manifest_path.read_text())
expected_keys = [
    "schema_version", "firmware_version", "factory_image",
    "factory_image_sha256", "update_image", "update_image_sha256",
]
if list(manifest) != expected_keys:
    raise SystemExit(f"unexpected manifest fields: {list(manifest)}")
if manifest["schema_version"] != 1 or manifest["firmware_version"] != firmware_version:
    raise SystemExit("manifest version does not match package inputs")
for image_key, checksum_key in (("factory_image", "factory_image_sha256"), ("update_image", "update_image_sha256")):
    image = manifest_path.parent / manifest[image_key]
    if not image.is_file() or hashlib.sha256(image.read_bytes()).hexdigest() != manifest[checksum_key]:
        raise SystemExit(f"manifest checksum does not match staged {image_key}")
PY

printf 'Built %s\n' "$package_path"
