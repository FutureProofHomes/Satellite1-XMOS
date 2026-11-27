# Audio DSP Pipeline

## Pipeline Stages

The Satellite1 audio pipeline processes 16 kHz, 2-channel (stereo mic) input
audio through five stages. The pipeline is split across two XMOS tiles:

```
Tile 1 (input side)              Tile 0 (output side)
+----------------------+         +---------------------------+
| 1. Static Delay      |         | 3. IC + VNR              |
| 2. AEC              | ~~>~~~> | 4. NS                    |
+----------------------+  port7  | 5. AGC                   |
                                 +---------------------------+
```

### Stage 1: Static Delay (Tile 1, optional)

- **Purpose:** Align mic and reference (speaker) audio in time.
- **Config:** `appconfINPUT_SAMPLES_MIC_DELAY_MS` (currently `0` = disabled).
- **Implementation:** FreeRTOS stream buffer. Positive value delays mics;
  negative value delays reference.
- **Skipped when:** `appconfINPUT_SAMPLES_MIC_DELAY_MS == 0` (current config).

### Stage 2: AEC — Acoustic Echo Cancellation (Tile 1)

- **Purpose:** Remove speaker echo from microphone signals.
- **Input:** 2 mic channels (Y) + 2 reference channels (X, from I2S speaker).
- **Output:** 2 echo-cancelled mic channels.
- **Config:**
  - `AEC_MAX_Y_CHANNELS = 2`
  - `AEC_MAX_X_CHANNELS = 2`
  - `AEC_MAIN_FILTER_PHASES = 10`
  - `AEC_SHADOW_FILTER_PHASES = 5`
- **Implementation:** `aec_process_frame_1thread()` from `fwk_voice` AEC library.
  Single-threaded variant (no parallel filter splits) to fit within one tile.
- **Side outputs:** `max_ref_energy` and `aec_corr_factor` (passed to AGC).

### Stage 3: IC + VNR — Interference Cancellation + Voice/Non-voice Recognition (Tile 0)

- **Purpose:**
  - **IC:** Suppress non-speech interference (babble noise, TV, etc.) using
    spectral subtraction informed by VNR.
  - **VNR:** TFLite Micro inference producing a voice/non-voice probability
    per frame. Used to gate IC adaptation and AGC behaviour.
- **Input:** 2 echo-cancelled channels (uses channel 0 as primary, channel 1
  as secondary for binaural processing).
- **Output:** 1 interference-cancelled channel (channel 0).
- **Config:** `VNR_AGC_THRESHOLD = 0.5` (voice probability threshold).
- **Implementation:**
  - `ic_filter()` — spectral interference cancellation
  - `ic_calc_vnr_pred()` — VNR feature extraction + TFLite inference
  - `ic_adapt()` — IC filter adaptation (gated by VNR output)
- **Side outputs:** `vnr_pred_flag` (passed to AGC), IC output stored in
  `aec_reference_audio_samples[0]` for debugging.

### Stage 4: NS — Noise Suppression (Tile 0)

- **Purpose:** Reduce background noise (fan, HVAC, room tone) using
  spectral gating.
- **Input:** 1 interference-cancelled channel.
- **Output:** 1 noise-suppressed channel.
- **Config:** `NS_FRAME_ADVANCE = 240` (matches pipeline frame size).
- **Implementation:** `ns_process_frame()` from `fwk_voice` NS library.
- **Side output:** NS output stored in `aec_reference_audio_samples[1]`
  for debugging.

### Stage 5: AGC — Automatic Gain Control (Tile 0)

- **Purpose:** Normalize output level to a target for downstream speech
  recognition (wake-word, ASR).
- **Input:** 1 noise-suppressed channel + metadata (VNR flag, AEC reference
  power, AEC correlation factor).
- **Output:** 1 gain-normalized channel (broadcast to both output channels).
- **Config:** `AGC_PROFILE_ASR` profile (tuned for speech recognition).
- **Implementation:** `agc_process_frame()` from `fwk_voice` AGC library.
- **Metadata:**
  - `vnr_flag`: 1 if speech detected (AGC targets speech level)
  - `aec_ref_power`: reference signal energy (AGC backs off when speaker active)
  - `aec_corr_factor`: AEC convergence indicator

## Frame Data Structure

The pipeline passes a `frame_data_t` struct between tiles (and between stages
within a tile):

```c
typedef struct {
    // Primary audio: 2 ch x 240 samples (mic, progressively processed)
    int32_t samples[2][240];

    // Reference audio: 2 ch x 240 samples (speaker, for AEC)
    int32_t aec_reference_audio_samples[2][240];

    // Passthrough copy of raw mic (pre-AEC), for debugging
    int32_t mic_samples_passthrough[2][240];

    // Per-frame context (set by Tile 1, consumed by Tile 0)
    int32_t vnr_pred_flag;          // Voice detected (0/1)
    float_s32_t max_ref_energy;     // Max reference channel energy
    float_s32_t aec_corr_factor;    // AEC correlation factor
    int32_t ref_active_flag;        // Reference signal active
} frame_data_t;
```

**Size:** ~10 KB per frame. Transferred over intertile port 7.

**Channel semantics after each stage (channel 0):**
- After AEC: echo-cancelled mic
- After IC: interference-cancelled
- After NS: noise-suppressed
- After AGC: level-normalized (final output)

## Pipeline Scheduling

Each tile runs its stages as a chain of FreeRTOS tasks using the
`generic_pipeline` framework from `fwk_voice`:

```
[input task] -> [stage_1 task] -> [stage_2 task] -> ... -> [output task]
```

- Each stage runs in its own FreeRTOS task with a dedicated stack.
- Inter-stage communication uses FreeRTOS queues (one frame in flight).
- The pipeline is lock-free between stages (single producer/consumer per queue).
- **Tile 1:** 2 stages (delay, AEC) → 2 pipeline tasks + input + output
- **Tile 0:** 3 stages (IC+VNR, NS, AGC) → 3 pipeline tasks + input + output

## Configuration

All pipeline configuration is defined in:

| File | Content |
|------|---------|
| `audio_pipelines/reference/fixed_delay/audio_pipeline_dsp.h` | Channel counts, frame advance, AEC phases, delay buffer size |
| `src/app_conf.h` | Sample rate, bypass flags, I2S config, task priorities |
| `bsp_config/SATELLITE1/SATELLITE1.cmake` | Hardware: MCLK, PDM freq, mic count, mic mapping |

### Key Parameters

| Parameter | Value | Location |
|-----------|-------|----------|
| Sample rate | 16 000 Hz | `appconfAUDIO_PIPELINE_SAMPLE_RATE` |
| Frame advance | 240 samples (15 ms) | `MIC_ARRAY_CONFIG_SAMPLES_PER_FRAME` |
| Mic channels | 2 | `MIC_ARRAY_CONFIG_MIC_COUNT` |
| Ref channels | 2 | `AP_MAX_X_CHANNELS` |
| AEC main phases | 10 | `AEC_MAIN_FILTER_PHASES` |
| AEC shadow phases | 5 | `AEC_SHADOW_FILTER_PHASES` |
| I2S output rate | 48 000 Hz | `appconfI2S_AUDIO_SAMPLE_RATE` |
| I2S upsample factor | 3x (16k→48k) | `appconfAUDIO_SPK_PL_SR_FACTOR` |
| Mic gain | 10x (fixed) | `mic_gain_10x()` in `main.c` |
| AGC profile | `AGC_PROFILE_ASR` | `audio_pipeline_t0.c:144` |

### Compile-Time Pipeline Selection

Stages can be individually disabled via preprocessor defines:

| Define | Effect |
|--------|--------|
| `appconfPIPELINE_BYPASS=1` | Disables ALL stages (bypass variant) |
| `appconfAUDIO_PIPELINE_SKIP_STATIC_DELAY=1` | Skips delay buffer |
| `appconfAUDIO_PIPELINE_SKIP_AEC=1` | Skips AEC |
| `appconfAUDIO_PIPELINE_SKIP_IC_AND_VNR=1` | Skips IC + VNR |
| `appconfAUDIO_PIPELINE_SKIP_NS=1` | Skips noise suppression |
| `appconfAUDIO_PIPELINE_SKIP_AGC=1` | Skips AGC |

These are set in `satellite1.cmake` based on the variant being built.

## Adding or Modifying a Stage

1. Add a `stage_*` function in the appropriate tile's `audio_pipeline_t*.c`.
2. Add the stage to the `stages[]` array in `audio_pipeline_init()`.
3. Add a corresponding entry to `stage_stack_sizes[]`.
4. Increment `stage_count`.
5. If the stage needs state, add a `static` state struct and initialize it in
   `initialize_pipeline_stages()`.
6. If the stage needs new configuration, add it to `audio_pipeline_dsp.h`.

## Source File Map

```
audio_pipelines/reference/fixed_delay/
├── audio_pipeline_dsp.h    # Frame struct, stage state structs, AEC config
├── audio_pipeline_t0.c     # Tile 0: IC+VNR, NS, AGC stages
├── audio_pipeline_t1.c     # Tile 1: delay, AEC stages
└── aec/
    ├── aec_process_frame_1thread.c  # Single-threaded AEC frame processor
    └── aec_memory_pool.h           # AEC memory pool sizing
```
