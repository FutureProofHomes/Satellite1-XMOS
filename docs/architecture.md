# System Architecture

## Overview

Satellite1 is a smart-speaker-style voice assistant satellite. It combines two
MCUs on a single PCB:

| Component | Role |
|-----------|------|
| **ESP32-S3** ([ESPHome](https://github.com/FutureProofHomes/Satellite1-ESPHome)) | Wi-Fi, Home Assistant integration, wake-word detection, voice assistant backend, device control |
| **XMOS XS3-A** (this firmware) | Real-time audio front-end: PDM mic capture, AEC/IC/NS/AGC DSP, I2S audio streaming to ESP32, USB DFU, LED ring, GPIO |

The XMOS chip is the audio "front end." It processes raw microphone audio and
streams the cleaned result to the ESP32-S3 over I2S. The ESP32 handles all
higher-level functions (Wi-Fi, cloud, wake-word, TTS).

## Data Flow

```
PDM Mics (2x MEMS)
       |
       v
+--------------------+
|  XMOS XS3-A       |
|                    |
|  Tile 1:          |
|    PDM decode     |
|    10x mic gain   |
|    [static delay] |
|    AEC (echo)     |
|                    |
|  ~~~ intertile ~~~ |  (port 7, frame_data_t)
|                    |
|  Tile 0:          |
|    IC + VNR       |
|    NS (noise)     |
|    AGC (gain)     |
|    I2S TX (48kHz) |
+--------------------+
       |
       |  I2S (48 kHz, 2ch, master)
       v
+--------------------+
|  ESP32-S3         |
|  (ESPHome)        |
|  - wake word      |
|  - VA backend     |
|  - Home Assistant |
+--------------------+
       |
       |  SPI (device control, v0x11)
       v
+--------------------+
|  XMOS servicers   |
|  - LED ring (WS2812)
|  - GPIO           |
|  - DFU (USB)      |
+--------------------+
```

## Inter-Peripheral Interfaces

| Interface | Direction | Detail |
|-----------|-----------|--------|
| **PDM** | Mics → XMOS | 2-channel PDM, 3.072 MHz clock, DDR mode |
| **I2S** | XMOS → ESP32 | 48 kHz, 2-channel, XMOS is master, 16-bit slot in 32-bit frame |
| **SPI** | ESP32 → XMOS | Device control protocol (v0x11): LED, GPIO, DFU trigger |
| **USB** | Host ↔ XMOS | DFU (Device Firmware Update) over USB, Tile 0 |
| **WS2812** | XMOS → LED ring | Neopixel LED ring, driven by Tile 0 |

## XMOS XS3-A Tile Utilization

The XS3-A has 2 tiles (14 cores total). The firmware uses both:

| Tile | Cores used | Responsibilities |
|------|-----------|-----------------|
| **Tile 1** | 4-5 | PDM mic input, 10x gain, static delay buffer (if configured), AEC (main + shadow filters), intertile TX |
| **Tile 0** | 5-6 | Intertile RX, IC + VNR inference, NS, AGC, I2S TX, USB DFU, SPI device control, LED ring, GPIO, FreeRTOS tasks |

The pipeline is split across tiles to distribute DSP load. Tile 1 handles the
compute-heavy AEC (adaptive filtering with 10+5 phases), while Tile 0 handles
the lighter IC/NS/AGC stages plus all I/O and control servicers.

## FreeRTOS Tasks (Tile 0)

Tile 0 runs a FreeRTOS scheduler with these tasks (in priority order):

1. **Pipeline task** (highest) — IC → NS → AGC stages, I2S output
2. **DFU servicer** — USB device firmware update state machine
3. **Device control servicer** — SPI command processing (LED, GPIO)
4. **LED ring task** — WS2812 output
5. **GPIO task** — GPIO input polling
6. **Idle / watchdog**

## Clock Architecture

| Clock | Frequency | Source |
|-------|-----------|--------|
| Core | 600 MHz | SW-PLL (software PLL) |
| PDM MCLK | 24.576 MHz | Tile 1 clock block A |
| PDM data | 3.072 MHz | Tile 1 clock block B |
| I2S BCLK | 48 kHz × 8 (32-bit) | Tile 0, I2S master |
| USB | 48 MHz | Internal |

The `sw_pll` library (`modules/sw_pll`) synthesizes the 600 MHz core clock.

## Firmware Variants

Three variants are built from the same source tree, selected at CMake
configure time via `FFVA_PIPELINES_INT`:

| Variant | Pipeline | Use case |
|---------|----------|----------|
| `satellite1_firmware_fixed_delay` | AEC→IC→VNR→NS→AGC (0 ms delay) | **Production** |
| `satellite1_firmware_adec` | AEC (with adaptive delay est)→IC→VNR→NS→AGC | Experimental |
| `satellite1_firmware_bypass` | Raw mic passthrough (no DSP) | Debugging / raw audio capture |

The `bypass` variant uses the same tile split but sets
`appconfPIPELINE_BYPASS=1`, which causes all DSP stages to be no-ops at
compile time (`#if appconfAUDIO_PIPELINE_SKIP_*`).

## Device Control

The ESP32-S3 controls XMOS peripherals via SPI using a custom protocol
(v0x11). See `docs/device-control-spi-protocol.md` for the full spec.

Registered resources on the current board:

| Resource ID | Function |
|-------------|----------|
| 200 | LED ring (WS2812) — set color, brightness, effects |
| 211 | GPIO input A — read digital inputs |
| 240 | DFU controller — trigger USB DFU mode |

## Flash Layout

The XMOS QSPI flash (16 MB) is partitioned:

| Partition | Size | Content |
|-----------|------|---------|
| Boot | 0x100000 (1 MB) | Flash loader + factory image |
| Data | Remainder | Filesystem (FAT) — currently unused |

The `.factory.bin` image contains both partitions. The `.upgrade.bin` is a
standalone firmware image for DFU updates (no boot loader).

## Versioning

Firmware version is embedded at build time by `versioning.py`. See
`docs/versioning.md` for the full scheme. The version is reported via the DFU
interface and controls the ESPHome `memory_flasher` component.
