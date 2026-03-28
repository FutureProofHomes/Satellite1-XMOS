# Satellite1 XMOS firmware

## Variants
**satellite1_firmware_fixed_delay**

Uses the 'Automatic Delay Estimation and Correction' pipeline of the sln_voice example repository.

**satellite1_firmware_empty**

A variant which bypasses the mic-pipeline. Hence, the raw mic signal is streamed to the ESP32-S3.

**sq66_firmware_{fixed_delay|empty}**

Firmware for developing purposes only. It runs on the  XK-VOICE-SQ66 evaluation board. 

## Firmware Files

**variant_name.factory.bin**

A complete image of the flash memory, including both the boot partition (containing the flash loader and factory image) and the data partition.

**variant_name.upgrade.bin**

A firmware upgrade image that can be uploaded through the Device Firmware Update (DFU) service. Requires a factory image with DFU support running on the device.


**variant_name.xe**

The XMOS executable (XE) binary format stores programs for XMOS devices and includes information about the system it is intended to run on, allowing support for multiple program loads, configurations and debugging.



## Running / Flashing via xTAG
> **Note**: The Satellite1 does not include an xTAG debugger. This option applies only when testing the firmware with a developer board like the SQ66 EVALUATION KIT. 

When the XMOS board is connected as a USB xTag device, the firmware can be run or flashed as follows:

Running without flashing:

```bash
xrun --xscope variant_name.xe
```

Flashing:
```bash
xflash --quad-spi-clock 50MHz --factory variant_name.xe --boot-partition-size 0x100000 --data variant_name_data_partition.bin
```


## Building the firmware locally

### Clone repository

```bash
git clone https://github.com/FutureProofHomes/Satellite1-XMOS.git
cd Satellite1-XMOS
git submodule update --init --recursive
```

### Setup XTC-Tools
Download XTX-15.3.1 from https://www.xmos.com/software-tools/

On Mac, the original software requires installing into `/Applications`. If you want to install into another directory, change `XMOS_TOOL_PATH` in `${INSTALL_DIR}/SetEnv.sh` to :
```bash
export XMOS_TOOL_PATH=${0:A:h};
```

### Setup Python Virtual Environment
The `xmos-ai-tools` python package is required for building the firmware modules.
It is recommended to install it into a virtual environment:

```bash
tools/env/python_env.sh --setup --with-tests
source .venv/bin/activate
```

The setup script always installs via `.venv/bin/python -m pip` so requirements are
not accidentally installed into another Python environment.

If you prefer manual setup:

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -r requirements_tests.txt
```

for later builds, activate the environment before calling cmake:
```bash
source .venv/bin/activate
```


### Creating factory and upgrade images

On Linux and Mac run:

```bash
cmake -B build --toolchain xmos_cmake_toolchain/xs3a.cmake
cd build

make create_flash_img_variant_name
make create_upgrade_img_variant_name
```

On Windows run:
```bash
cmake -G Ninja -B build --toolchain xmos_cmake_toolchain/xs3a.cmake
cd build

ninja create_flash_img_variant_name
ninja create_upgrade_img_variant_name
```

### Building the XMOS executable only (.xe file)
Run the following commands in the root folder to build the firmware.

On Linux and Mac run:

```bash
cmake -B build --toolchain xmos_cmake_toolchain/xs3a.cmake
cd build

make variant_name
```

On Windows run:
```bash
cmake -G Ninja -B build --toolchain xmos_cmake_toolchain/xs3a.cmake
cd build

ninja variant_name
```

### Building the XMOS executable with debug/xscope capabilities (.xe file)
Run the following commands in the root folder to build the firmware.

On Linux and Mac run:

```bash
cmake -B build --toolchain xmos_cmake_toolchain/xs3a.cmake -DUSE_DEV_MODE=1
cd build

make variant_name
```

On Windows run:
```bash
cmake -G Ninja -B build --toolchain xmos_cmake_toolchain/xs3a.cmake -DUSE_DEV_MODE=1
cd build

ninja variant_name
```

### Debugging with SQ66-DEV-BOARD
```bash
xgdb variant-name.xe
connect --xscope
run
```

