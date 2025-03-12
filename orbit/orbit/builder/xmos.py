import os
import subprocess
import select

from pathlib import Path

from orbit import PROJ_ROOT, XTC_PATH

SOURCE_CMD="zsh"


def setup_xtc_env(xtc_path:str=XTC_PATH) -> None:
    print( f"Activating XTC environment at {xtc_path} ..." )
    script = os.path.join(xtc_path, "SetEnv.sh" )
    pipe = subprocess.Popen( f"{SOURCE_CMD} {script} && env -0", stdout=subprocess.PIPE, shell=True)
    output = pipe.communicate()[0].decode('utf-8')
    output = output[:-1] # fix for index out for range in 'env[ line[0] ] = line[1]'

    env = {}
    # split using null char
    for line in output.split('\x00'):
        line = line.split( '=', 1)
        env[ line[0] ] = line[1]

    os.environ.update(env)

def setup_py_env(env_path:str) -> None:
    print( f"Activating Python environment at {env_path} ..." )
    script = os.path.join(env_path, "bin", "activate" )
    pipe = subprocess.Popen( f". {script} && env -0", stdout=subprocess.PIPE, shell=True)
    output = pipe.communicate()[0].decode('utf-8')
    output = output[:-1] # fix for index out for range in 'env[ line[0] ] = line[1]'

    env = {}
    # split using null char
    for line in output.split('\x00'):
        line = line.split( '=', 1)
        env[ line[0] ] = line[1]

    os.environ.update(env)


def run_command(command, cwd=None):
    """Runs a shell command and prints the output."""
    env = os.environ.copy()
    print( f"CMD: {command}")
    process = subprocess.Popen(command, shell=True, cwd=cwd,
                               #stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, env=env)
    
    #while process.stdout.readable():
    #    line = process.stdout.readline()
    #    
    #    if not line:
    #        break
    #    print(line, end="")  # Print output in real-time


    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"Command failed: {command}")



def build_firmware( build_dir:Path, variant:str, src_dir:Path=PROJ_ROOT, clean:bool=False, defines:list[str] = [] ) -> bool:
    """Configures and builds a CMake project using Make."""
    
    setup_xtc_env(XTC_PATH)
    setup_py_env("/Users/mischa/Projects/FutureProofHomes/Satellite1-XMOS-15.3/.venv")
    
    run_command( "which python3" )

    full_build_dir = src_dir / build_dir
    if clean and full_build_dir.exists():
        print(f"Cleaning build directory: {build_dir}")
        subprocess.run(f"rm -rf {build_dir}", shell=True, cwd=src_dir)

    os.makedirs( src_dir / build_dir, exist_ok=True)

    defstr = " ".join([ "-D {}".format(d) for d in defines ])

    print(f"Running CMake configuration in '{build_dir}'...")
    run_command(f"cmake -B {build_dir} --toolchain xmos_cmake_toolchain/xs3a.cmake {defstr}", cwd=src_dir)


    print(f"Building {variant}...")
    run_command(f"make -C {build_dir} {variant} -j", cwd=src_dir)


def usb_dfu_upload( device:str, image:Path, reset:bool=True ) -> bool :
    print( f"Uploading {image} to alt=1 of device: {device}...")
    run_command( f"dfu-util -d {device} -a 1 -D {str(image)} {'-R' if reset else ''}" )


def usb_dfu_download( device:str, dst:Path ) -> bool :
    print( f"Downloading alt=1 of device: {device} to {dst}...")
    run_command( f"dfu-util -d {device} -a 1 -U {str(dst)} " )


def reset_device(xtag_id:str) -> bool:
    print( "Resetting device..." )
    run_command( f"xrun --adapter-id {xtag_id} --reset" )