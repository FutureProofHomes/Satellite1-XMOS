
BOARD = "Satellite1"
VARIANT = "test_rtos_dummy"

CASE_STUDY = "test_delayConfigs_fdPipeline_Sat1"

ref_wav_files = [
    ("piper", "/Users/mischa/Projects/AEC/nexus_reference_signal_16kHZ_mono.wav", 55),
   # ("speech", "", 0),
   # ("music", "", 0),
   # ("chirp", "", 0)
]

test_params = {
    #"delayCfg" : [0, 5, -5, 10, -10, 20, -20, 2, -2, 1, -1, 15, -15, 50, -50, 100, -100],
    #"delayCfg" : [-20, 2, -2, 1, -1, 15, -15, 50, -50, 100, -100],
    "delayCfg" : [-10, 1, 50],
}

from pathlib import Path
import sys
import os

PROJ_ROOT = Path(__file__).parent.parent.parent
sys.path.append(str(PROJ_ROOT))

RES_DIR = Path(__file__).parent / "results" / CASE_STUDY

import itertools
import time
from orbit.builder.xmos import build_firmware, usb_dfu_upload, reset_device
from orbit.audio.sox import run_playback_and_record
from orbit.audio.analysis import calc_channel_variances
from orbit import BOARD_USB_IDS, BOARD_SND_CARD_NAMES
from orbit.audio.utils import read_wav_wave

def test_program(test_case_id:str):
    os.makedirs( RES_DIR / test_case_id, exist_ok=True)
    
    for run in range(5):
        for retry in range(5):
            try:
                out_file = RES_DIR / test_case_id / f"test_r{run}.wav"
                print(f"Recording: {str(out_file)}")
                run_playback_and_record(
                    play_file=ref_wav_files[0][1],
                    out_file=str(out_file),
                    device=BOARD_SND_CARD_NAMES[BOARD]
                )
                break
            except Exception as e:
                print( f"Error in run_playback_and_record: {e}")
                if retry == 4:
                    sys.exit(1)
                reset_device(BOARD_XTAG_IDS[BOARD])
                time.sleep(5)                

        print( calc_channel_variances(str(out_file)) )
        

def run_test_cases():
    # all test_params combinations
    test_cases = itertools.product(*[[ (k, e) for e in v ] for k,v in test_params.items()])

    for test_case in test_cases:
        test_case_id = CASE_STUDY + "_" + "__".join( [f"{k}_{v}" for k,v in sorted(test_case)])
        print( f"TEST CASE: {test_case_id}" )

        params = dict(test_case)
        cmake_defines = [
            f"appconfINPUT_SAMPLES_MIC_DELAY_MS={params['delayCfg']}"
        ]
        variant="test_rtos_dummy"
        build_dir = f"build_{CASE_STUDY}"
        build_firmware( 
            build_dir=build_dir,
            src_dir=PROJ_ROOT,
            variant=f"create_upgrade_img_{variant}",
            clean=True,
            defines=cmake_defines
        )
        
        target = PROJ_ROOT / build_dir / f"{variant}.upgrade.bin"
        if not target.exists():
            print( f"Build failed, target {target} not found..." )
            sys.exit(1)

        usb_dfu_upload( 
            device=BOARD_USB_IDS[BOARD],
            image=target
        )
        
        time.sleep(10)
        test_program(test_case_id)



run_test_cases()
