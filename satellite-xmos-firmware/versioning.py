import argparse
import dataclasses
import datetime
import filecmp
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap
from typing import Any, Union

PROJ_ROOT = Path(__file__).parent.parent
VERSION_FILE = PROJ_ROOT / "firmware_version.txt"
DEFAULT_DEV_TRACK_PATH = PROJ_ROOT / "dev_tracking"
DEFAULT_BUILD_DIR = PROJ_ROOT / "build"
VERSION_HEADER_FILE = Path(__file__).parent / "src" / "version.h"

TO_TRACK = [
    "{variant}.factory.bin",
    "{variant}.factory.md5",
    "{variant}.xe"
]

PRE_RELEASES = ["none","alpha","beta","rc","dev"]
VERSION_REGEX = re.compile(r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)([-.]?(?P<prerelease>[a-zA-Z]+)(\.(?P<counter>\d+))?)?$")

VERSION_HEADER_TMPL = """/* Auto-generated by make using versioning.py */
#pragma once

/* {str_repr} */
#define APP_VERSION_MAJOR {major}
#define APP_VERSION_MINOR {minor}
#define APP_VERSION_PATCH {patch}
#define APP_VERSION_PRERELEASE {pre_release}
#define APP_VERSION_COUNTER {counter}
"""

EMBED_XMOS_YAML_TMPL = """
memory_flasher:
  - platform: satellite1
    id: xflash
    embed_flash_image:
      image_version: {version}
      image_file: {image_file}
      md5_file: {md5_file} 
"""



@dataclasses.dataclass(order=True)
class XMOSVersion:
    major: int
    minor: int
    patch: int
    pre_release: int = 0
    pre_counter: int = 0

    def counter_inc(self):
        self.pre_counter += 1
        if self.pre_counter == 255 :
            print( "WARNING: Resetting dev counter to 1!")
            self.pre_counter = 1
        return self
    
    def set_to_dev(self):
        if PRE_RELEASES[self.pre_release] == "dev":
            return
        self.pre_release = PRE_RELEASES.index("dev")
        self.pre_counter = 0
        return self
    
    @property
    def base_version_string(self):
        return f"v{self.major}.{self.minor}.{self.patch}"
    
    @property
    def is_dev(self):
        return PRE_RELEASES[self.pre_release] == "dev"

    @classmethod
    def from_string(cls, vstr: str) -> "XMOSVersion":
        match = VERSION_REGEX.match(vstr)
        if not match:
            raise SystemExit(f"Invalid version string: {vstr}")

        groups = match.groupdict()
        if groups["prerelease"] and groups["prerelease"] not in PRE_RELEASES:
            raise SystemExit(f"Invalid pre_release string: {groups['prerelease']}")
        
        return cls(
            major=int(groups["major"]),
            minor=int(groups["minor"]),
            patch=int(groups["patch"]),
            pre_release=PRE_RELEASES.index(groups["prerelease"]) if groups["prerelease"] else 0,
            pre_counter=int(groups["counter"]) if groups["counter"] else 0
        )


    @classmethod
    def from_header_file(cls, header_file:Path) -> "XMOSVersion":
        if not header_file.exists():
            return None
        
        parsed_version = {}
        with header_file.open("r") as f:
            for line in f:
                mObj = re.search( r'^[\t ]*#define APP_VERSION_([A-Z]+) (\d+)', line)
                if mObj :
                    parsed_version[mObj.group(1)] = int(mObj.group(2))
        
        try:
            return cls(
                parsed_version.get( "MAJOR", 0),
                parsed_version.get( "MINOR", 0),
                parsed_version.get( "PATCH", 0),
                parsed_version.get( "PRERELEASE", 0),
                parsed_version.get( "COUNTER", 0)
            )
        except:
            print( f"Couldn't receive version from heder file {header_file} ")
            sys.exit(1)


    def __str__(self):
        vstr = self.base_version_string
        if self.pre_release > 0 :
            vstr += f"-{PRE_RELEASES[self.pre_release]}"
        if self.pre_counter > 0 :
            vstr += f".{self.pre_counter}"     
        return vstr

    def __repr__(self):
        return f"XMOSVersion('{str(self)}')"



@dataclasses.dataclass
class GitInfo:
    branch: str
    commit: str
    last_tag: Union[str, None] = None
    patch_str: str = ""
    
    @classmethod
    def from_ws(cls, repo_root:str=PROJ_ROOT) -> tuple[str]:
        try:
            branch = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"], 
                    cwd=repo_root, capture_output=True, text=True, check=True
                ).stdout.strip() 
            commit_hash = subprocess.run(
                    ["git", "rev-parse", "--short" ,"HEAD"],
                    cwd=repo_root, capture_output=True, text=True, check=True
                ).stdout.strip() 
        
            try:
                last_tag =subprocess.run(['git', 'describe', '--tags', '--abbrev=0'], 
                        cwd=repo_root, capture_output=True, text=True,  check=True
                    ).stdout.strip()        
            except:
                last_tag = None # current repo doesn't have any tag

            patch_str = subprocess.run(['git', 'diff'], 
                    cwd=repo_root, capture_output=True, text=True,  check=True
                ).stdout
            


            return cls(branch, commit_hash, last_tag, patch_str)
        
        except subprocess.CalledProcessError:
            print("Calling git failed!")
            sys.exit(1)
    
    def as_dict(self, skip_patch_str=False):
        data_dict = dataclasses.asdict(self)
        if skip_patch_str:
            data_dict.pop("patch_str")
        return data_dict

    def __str__(self):
        return f"{self.commit}" + ("+patch" if self.patch_str else "") + f"@{self.branch}"

    def __repr__(self):
        return f"GitInfo({str(self)})"



class TrackDevEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, GitInfo):
            return obj.as_dict(skip_patch_str=True)
        if dataclasses.is_dataclass(obj):
            return dataclasses.asdict(obj)
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        if isinstance(obj, Path):
            return obj.as_uri()
        return super().default(obj)


@dataclasses.dataclass
class TrackedDevBuild:
    version: XMOSVersion
    variant: str 
    build_time: datetime.datetime
    git_info: Union[GitInfo, None] = None
    track_path: Union[Path, None] = None
    patch_file_md5: Union[str, None] =  None

    def __eq__(self, other):
        return (
            self.variant == other.variant and
            self.git_info == other.git_info and
            self.patch_file_md5 == other.patch_file_md5
        )
    def add_patch_file(self):
        pass
    
    def serialize(self):
        shallow_dict = {field.name: getattr(self, field.name) for field in dataclasses.fields(self)}
        return json.dumps(shallow_dict, cls=TrackDevEncoder)
    
    def store(self, tracking_path: Path) -> None:
        dev_path = tracking_path / str(self.version)
        if dev_path.exists():
            print( f"Path {dev_path} already exists" )
            sys.exit(1)
        try: 
            dev_path.mkdir(parents=True)
        except:
            print( f"Couldn't create directory {dev_path}")
            sys.exit(1)
        self.track_path = dev_path
        shallow_dict = {field.name: getattr(self, field.name) for field in dataclasses.fields(self)}
        with (dev_path / "info.json").open("w") as f:
            json.dump(shallow_dict, f, indent="", cls=TrackDevEncoder)

    @classmethod
    def latest(cls, dev_track_path:Path, base_version: Union[XMOSVersion,None] = None) -> "TrackedDevBuild":
        if not dev_track_path.exists():
            return None
        dev_tracks = sorted(
            [ (XMOSVersion.from_string(f.name),f) 
                for f in dev_track_path.iterdir() 
                if (f.is_dir() and (base_version is None or f.name.startswith(base_version.base_version_string)))
            ],reverse=True)
        if len(dev_tracks):
            return cls.load(dev_tracks[0][1])
    
    @classmethod
    def load(cls, track_path: Path) -> "TrackedDevBuild":
        if not track_path.exists():
            print( f"Can't load build info from: {str(track_path)}" )
            sys.exit(1)
        
        with (track_path / "info.json").open("r") as f:
            obj_dict = dict(json.load(f))

        version = XMOSVersion(**obj_dict["version"])    
        variant = obj_dict["variant"]
        build_time = datetime.datetime.fromisoformat(obj_dict["build_time"])
        git_info = GitInfo(**obj_dict["git_info"])
        patch_file = track_path / "build_time.patch"
        if patch_file.exists():
            with patch_file.open("r") as f:
                git_info.patch_str = f.read()
        patch_file_md5 = obj_dict["patch_file_md5"]
        
        return cls( 
            version=XMOSVersion.from_string(track_path.name), 
            variant=variant,
            build_time=build_time,
            git_info=git_info,
            track_path=track_path,
            patch_file_md5=patch_file_md5
        )
        
def create_patch_file( repo_root:Path, patch_file:Path ) -> str:
    try:
        with patch_file.open("w") as f:
            subprocess.run(
                        ["git", "diff" ], 
                        cwd=repo_root, stdout=f
            )
    except:
        print( "Error while trying to create patch file.")
        sys.exit(1)

    md5 = None
    with patch_file.open("rb") as f:
        md5 = hashlib.md5(f.read()).hexdigest()
    
    return md5



def create_version_header_file(file_path:Path, version: XMOSVersion) -> None :
    with file_path.open("w") as f:
        f.write( VERSION_HEADER_TMPL.format(
            str_repr=str(version),
            major=version.major,
            minor=version.minor,
            patch=version.patch,
            pre_release=version.pre_release,
            counter=version.pre_counter
        ))

def create_variant_version_file(file_path:Path, version: XMOSVersion) -> None:
    with file_path.open("w") as f:
        f.write( str(version) )

def create_yaml_import(build_dir:Path, variant:str, version: XMOSVersion) -> None:
    with (build_dir / "embed_flash_imag.yaml").open("w") as f:
        f.write( EMBED_XMOS_YAML_TMPL.format(
            version=str(version),
            image_file= build_dir / (variant + ".factory.bin"),
            md5_file= build_dir / (variant + ".factory.md5")
        ))


def track_dev_build(args: argparse.Namespace) -> TrackedDevBuild:
    dev_track_path = DEFAULT_DEV_TRACK_PATH
    git_info = GitInfo.from_ws()
    last_tag_version = XMOSVersion.from_string(git_info.last_tag)
    
    dev_build = TrackedDevBuild(
        version = last_tag_version.set_to_dev(),
        variant=args.variant,
        build_time=datetime.datetime.now(),
        git_info=git_info
    )
    
    patch_file = args.build_dir / "build_time.patch"
    if git_info.patch_str:
        md5 = create_patch_file( ".", patch_file )
        dev_build.patch_file_md5 = md5
    
    last_dev_build = TrackedDevBuild.latest(
        dev_track_path,
        last_tag_version
    )

    if last_dev_build is None or last_dev_build != dev_build :
        if not last_dev_build is None :
            dev_build.version = last_dev_build.version
        dev_build.version.counter_inc()
        
        dev_build.store(dev_track_path)
        if git_info.patch_str and patch_file.exists():
            shutil.move( patch_file, dev_build.track_path )
        return dev_build
    
    return last_dev_build




def get_version(args: argparse.Namespace) -> XMOSVersion:
    """
    Resolves the firmware version based on the provided arguments.

    - If `args.version` is specified, it is used directly as the version string.
    - Otherwise, the version is read from `args.infile`.

    Special Handling:
    - If the given version string is 'dev':
      - The last Git tag is retrieved as the base version.
      - '-dev' is appended to indicate a development version.
    - If `args.track` is enabled (in addition to 'dev'):
      - The script tracks each development build in `args.track_path`.
      - A build counter is incremented and appended to the version string.
      - Example: `1.2.3-dev.10` (10th tracked build of `1.2.3-dev`).

    Args:
        args (argparse.Namespace): Parsed command-line arguments.

    Returns:
        XMOSVersion: The resolved firmware version.
    """
    if args.version is None:
        version_file = args.infile
        if not version_file.exists():
            print(f"Version File {VERSION_FILE} does not exists.")
            sys.exit(1)
        
        vstr = ""
        with version_file.open("r") as f:
            vstr = f.readline()
    else:
        vstr = args.version
    
    if not vstr == "dev":
        return XMOSVersion.from_string(vstr)

    if "track" in args and args.track :
        return track_dev_build(args).version
    
    git_info = GitInfo.from_ws()
    tag_version = XMOSVersion.from_string(git_info.last_tag)
    return tag_version.set_to_dev()


def print_info(args: argparse.Namespace) -> None:
    git_info = GitInfo.from_ws() 
    from_header_file = XMOSVersion.from_header_file(VERSION_HEADER_FILE)
    version = get_version( args )
    tracked_build = None
    if version.is_dev and from_header_file:
        track_path = args.track_root / str(from_header_file)
        if track_path.exists():
            tracked_build = TrackedDevBuild.load(track_path)

    print( f"Current source: {git_info}" )
    print( f"{VERSION_HEADER_FILE.relative_to(Path.cwd())}: {'not found' if from_header_file is None else str(from_header_file)}")
    if tracked_build:
        ws_build_xe = args.build_dir / (tracked_build.variant + ".factory.bin")
        tracked_build_xe = tracked_build.track_path / (tracked_build.variant + ".factory.bin")
        same_build = ws_build_xe.exists() and tracked_build_xe.exists() and filecmp.cmp(tracked_build_xe, ws_build_xe)            
        print( textwrap.dedent(f"""\
        Found tracked dev-build: {str(tracked_build.version)}
            Variant: {tracked_build.variant}
            Build-Time: {tracked_build.build_time}
            source: {str(tracked_build.git_info) + (" (differs)" if git_info != tracked_build.git_info else " (matches)")}
            {(tracked_build.variant + ".factory.bin: ") + ("(Not found or differ)" if not same_build else "(matches)")}     
        """
        ))



# Command: build
def set_firmware_version(args: argparse.Namespace) -> None:
    version = get_version(args)
    create_version_header_file(VERSION_HEADER_FILE, version)
    

def install_targets(args: argparse.Namespace) -> None:
    version = get_version(args)
    create_yaml_import(args.build_dir, args.variant, version)
    if version.is_dev :
        track_path = track_dev_build(args).track_path 
        for file in TO_TRACK:
            shutil.copy( args.build_dir / file.format(variant=args.variant), track_path)
    
    

def main():
    print(sys.version)
    parser = argparse.ArgumentParser(description="Manages XMOS firmware versions.",formatter_class=argparse.RawTextHelpFormatter)
    # --version and --infile are mutual exclusive
    exclusive_group = parser.add_mutually_exclusive_group(required=False)
    exclusive_group.add_argument(
        "--version", 
        nargs=1, 
        action="store", 
        default=None,
        help=textwrap.dedent("""\
            Specify the firmware version manually.
            If set to 'dev':
              - The latest Git tag is used as the base version.
              - '-dev' is appended to indicate a development version.
        """)
    )
    exclusive_group.add_argument(
        "--infile",  
        nargs=1, 
        action="store", 
        default=None,
        help=textwrap.dedent("""\
            Specify a file that contains the firmware version to use.
            If not provided, the default file '{PROJECT_ROOT}/firmware_version.txt' is assumed.
        """)
    )
    parser.add_argument(
        "--build-dir", 
        nargs=1,
        action="store",
        default=DEFAULT_BUILD_DIR,
        help="CMake build folder. Default: '{PROJECT_ROOT}/build'"
    )
    
    parser.add_argument(
        "--track-root", 
        nargs=1, 
        action="store", 
        default=DEFAULT_DEV_TRACK_PATH, 
        help="Folder to keep tracked dev builds. Default: '{PROJECT_ROOT}/dev_tracking'"
    )
    
    
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")
    
    info_parser = subparsers.add_parser("info", help="Show workspace version information")
    info_parser.set_defaults(func=print_info)

    build_parser = subparsers.add_parser("build", help="Pass XMOS firmware version to build system.")
    build_parser.add_argument("variant", help="")
    build_parser.add_argument("--track", action="store_true", default=False, help="")
    build_parser.set_defaults(func=set_firmware_version)

    install_parser = subparsers.add_parser("track", help="Copy variant targets to tracked build folder.")
    install_parser.add_argument("variant", help="")
    install_parser.set_defaults(func=install_targets)
    
    args = parser.parse_args()
    if args.version is None and args.infile is None:
        if VERSION_FILE.exists():
            args.infile = VERSION_FILE
        else:
            parser.error("{VERSION_FILE} not found. Use --version or --infile, or ensure 'firmware_version.txt' exists.")

    if args.command == "track":
        args.track = True

    func = getattr(args, "func", None)

    if func:
        func(args)
    else:
        parser.print_help()


if __name__ == "__main__" :
    main()