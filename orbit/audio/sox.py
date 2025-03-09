import subprocess
import time

def run_playback_and_record( play_file:str, out_file:str, device:str ) -> None :
    """Run playback and record in parallel."""
    print( f"Running playback and record for {play_file} on device {device} ..." )
    
    cmd = f'sox -t coreaudio {device}  --channels=6 --rate=16000 -b 16 --encoding=signed-integer --endian=little --no-dither -t wavpcm "{out_file}" &'
    cmd += "SOX_PID=$!; "
    cmd += f'sox -t wav "{play_file}" -t coreaudio {device}'
    cmd += "&& kill $SOX_PID"
    timeout_s = 90
    try:
        p = subprocess.run(cmd, timeout=timeout_s, text=True, shell=True)
    except subprocess.TimeoutExpired:
        print(f'Timeout for {cmd} ({timeout_s}s) expired')
        raise subprocess.TimeoutExpired

    time.sleep(2)
