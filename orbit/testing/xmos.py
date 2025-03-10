from pathlib import Path
import subprocess
import os

from orbit.builder.xmos import setup_xtc_env

def run_firmware(firmware:Path, xtag_id:str) -> subprocess.Popen:
    setup_xtc_env()
    xrun_args = ["xrun", "--io", "--adapter-id", xtag_id, str(firmware.absolute())]
    env = os.environ.copy()
    return subprocess.Popen(xrun_args, env=env)