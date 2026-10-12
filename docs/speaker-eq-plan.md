# Speaker EQ Architecture and Implementation Plan

## Status

This document records the agreed design for adding speaker equalization to the
Satellite1 XMOS firmware. It covers the reusable EQ library, the first serial
speaker pipeline, runtime configuration, and the planned device-control
integration. It also records the intended direction for a later active
crossover pipeline.

The initial implementation uses `lib_audio_dsp` v1.5.0 through the native CMake
adapter at `modules/lib_audio_dsp_adapter`.

## Goals

- Provide a reusable, caller-owned speaker EQ library under `modules/fph`.
- Support stereo-linked and mono speaker processing.
- Support Butterworth and Linkwitz-Riley high-pass and low-pass designs with
  12 dB/octave and 24 dB/octave slopes.
- Support five independently configurable parametric peaking filters.
- Support one configurable high-shelf filter.
- Support configurable pre-gain and output clipping.
- Keep coefficient generation out of the real-time audio processing path.
- Apply runtime changes atomically at speaker-frame boundaries.
- Prepare the API for asynchronous control through the existing SPI/device-
  control framework.
- Preserve a post-EQ AEC reference that matches the signal sent to the speaker
  output.

## Initial Non-Goals

- Click-free runtime transitions are not required in the first implementation.
- EQ settings will not initially be persisted to flash.
- The first pipeline will not implement an active crossover or an LPF in its
  serial signal path.
- The generated `lib_audio_dsp` Stage and Python pipeline framework will not be
  used.
- Device-control callbacks will not perform floating-point coefficient design.

## Architecture

The dependency direction is:

```text
serial speaker EQ pipeline
    -> fph::speaker_eq
        -> audio_dsp::lib_audio_dsp
            -> lib_xcore_math
```

The reusable library owns:

- Semantic EQ configuration types.
- Configuration validation.
- HPF and LPF coefficient design.
- Parametric peak and high-shelf coefficient design.
- Fixed-point coefficient programs.
- Per-channel filter state.
- Frame processing.
- Pre-gain and output clipping.

The speaker pipeline owns:

- The compiled product preset.
- Planar speaker-frame adaptation.
- The active `speaker_eq_t` instance.
- Applying a prepared program at a frame boundary.
- Passing processed frames to the existing speaker output callback.

The future device-control integration owns:

- SPI wire encoding and decoding.
- Resource and command registration.
- Request queueing.
- Requested/applied generation tracking.
- A control worker that generates complete coefficient programs.
- Publishing prepared programs to the audio stage.

## Source Layout

### Reusable library

```text
modules/fph/speaker_eq/
├── CMakeLists.txt
├── README.md
├── api/
│   └── speaker_eq.h
├── src/
│   ├── speaker_eq.c
│   └── speaker_eq_design.c
└── test/
    ├── CMakeLists.txt
    ├── test_speaker_eq.c
    └── test_speaker_eq.py
```

The CMake targets will be:

```text
fph_speaker_eq
fph::speaker_eq
```

The library will have no FreeRTOS, device-control, SPI, hardware, or firmware-
global dependencies.

### Serial speaker pipeline

```text
satellite-xmos-firmware/audio_pipelines/speaker/serial_eq/
├── speaker_pipeline.c
├── speaker_eq_preset.c
└── speaker_eq_preset.h
```

The planned CMake alias is:

```text
sln_voice::app::ffva::sp::serial_eq
```

The existing passthrough pipeline remains available as a separate target.

### Future crossover pipeline

The first change will add only a planning document:

```text
satellite-xmos-firmware/audio_pipelines/speaker/crossover_eq/README.md
```

No crossover pipeline source will be added in the initial implementation.

## Signal Contract

- Input and output samples are signed 32-bit PCM values.
- Full-scale positive is `INT32_MAX`.
- Full-scale negative is `INT32_MIN`.
- The initial speaker sample rate is 48 kHz.
- The speaker pipeline frame contains 720 samples per channel.
- The pipeline frame layout is planar: `samples[channel][sample]`.
- The EQ processes frames in place.
- Filter state persists across frame boundaries.
- Coefficients are shared between channels in stereo-linked mode.
- Filter state is never shared between channels.

## Channel Modes

```c
typedef enum {
    SPEAKER_EQ_MODE_STEREO_LINKED,
    SPEAKER_EQ_MODE_MONO,
} speaker_eq_channel_mode_t;
```

### Stereo-linked mode

Both channels use the same coefficient program with independent filter state:

```text
Left  -> pre-gain -> EQ with left state  -> clip -> I2S left
Right -> pre-gain -> EQ with right state -> clip -> I2S right
```

### Mono mode

The input is averaged before EQ processing:

```c
mono = (int32_t)(((int64_t)left + right) / 2);
```

The 64-bit intermediate prevents overflow when adding two full-scale samples.
Signed division rounds toward zero. Averaging preserves full-scale headroom and
does not add the 3 dB gain associated with an equal-power sum.

The mono sample is processed once and duplicated to both output channels:

```text
Left ---\
         +-> average -> pre-gain -> one EQ state -> clip -+-> I2S left
Right --/                                                +-> I2S right
```

Only the first channel-state bank advances in mono mode. The second bank remains
cleared, reducing EQ processing work by approximately half relative to stereo.

### Bypass behavior

Channel routing and EQ bypass are separate concepts:

- Stereo plus bypass is bit-exact stereo passthrough.
- Mono plus bypass performs only averaging and duplication.
- Bypass skips pre-gain, biquad processing, and output clipping.

## Serial EQ Topology

The serial pipeline uses a fixed eight-section cascade:

| Sections | Function |
| --- | --- |
| `0..1` | High-pass filter |
| `2..6` | Five parametric peaking filters |
| `7` | High-shelf filter |

Disabled or unused sections contain bypass coefficients. Keeping all eight
slots present gives every configuration the same runtime topology and stable
band identifiers for future device control.

The serial pipeline intentionally contains no LPF. It assumes that a hardware
crossover follows the amplifier.

## Pass-Filter Designs

The reusable library will expose both high-pass and low-pass coefficient design
so that the later crossover pipeline can reuse the same validated code.

```c
typedef enum {
    SPEAKER_EQ_PASS_BYPASS,
    SPEAKER_EQ_PASS_BUTTERWORTH_12,
    SPEAKER_EQ_PASS_BUTTERWORTH_24,
    SPEAKER_EQ_PASS_LINKWITZ_RILEY_12,
    SPEAKER_EQ_PASS_LINKWITZ_RILEY_24,
} speaker_eq_pass_mode_t;
```

The designs map to second-order sections as follows:

| Design | Sections |
| --- | --- |
| Butterworth 12 | One section with `Q = 0.70710678` |
| Butterworth 24 | One section with `Q = 0.54119610`, then one with `Q = 1.30656297` |
| Linkwitz-Riley 12 | One section with `Q = 0.5` |
| Linkwitz-Riley 24 | Two identical sections with `Q = 0.70710678` |

`adsp_design_biquad_linkwitz()` must not be used for Linkwitz-Riley crossover
design. That API implements a Linkwitz Transform for changing loudspeaker
low-frequency behavior, not a Linkwitz-Riley crossover.

The library will use `adsp_design_biquad_highpass()` and
`adsp_design_biquad_lowpass()` to build these sections.

## Parametric And Shelf Filters

Each parametric band contains:

```c
typedef struct {
    bool enabled;
    float frequency_hz;
    float q;
    float gain_db;
} speaker_eq_parametric_t;
```

Parametric bands use `adsp_design_biquad_peaking()`.

The high shelf contains:

```c
typedef struct {
    bool enabled;
    float frequency_hz;
    float q;
    float gain_db;
} speaker_eq_high_shelf_t;
```

The shelf uses `adsp_design_biquad_highshelf()`.

## Semantic Configuration

```c
#define SPEAKER_EQ_CHANNEL_COUNT 2
#define SPEAKER_EQ_PEAK_COUNT 5
#define SPEAKER_EQ_SECTION_COUNT 8

typedef struct {
    speaker_eq_channel_mode_t channel_mode;
    bool bypass;

    float pregain_db;
    float clip_level_dbfs;

    speaker_eq_pass_mode_t hpf_mode;
    float hpf_frequency_hz;

    speaker_eq_parametric_t peak[SPEAKER_EQ_PEAK_COUNT];
    speaker_eq_high_shelf_t high_shelf;
} speaker_eq_config_t;
```

The sample rate is supplied separately rather than stored as an adjustable
filter parameter.

## Limits And Validation

The library applies two validation layers.

### Hard safety checks

- All floating-point values must be finite.
- Sample rate must be nonzero.
- Frequencies must satisfy `0 < frequency < sample_rate / 2`.
- Q must be greater than zero.
- Enum values must be recognized.
- The active filter count must not exceed eight sections.
- Fixed-point coefficients and left shifts must be representable.
- Quantized poles must remain inside the unit circle.
- Clip level must not exceed 0 dBFS.

### Configurable product policy

```c
typedef struct {
    float minimum_frequency_hz;
    float maximum_frequency_hz;
    float minimum_q;
    float maximum_q;
    float minimum_peak_gain_db;
    float maximum_peak_gain_db;
    float minimum_shelf_gain_db;
    float maximum_shelf_gain_db;
    float minimum_pregain_db;
    float maximum_pregain_db;
    float minimum_clip_level_dbfs;
    float headroom_margin_db;
    bool enforce_headroom;
} speaker_eq_limits_t;
```

Proposed initial serial-pipeline policy:

| Parameter | Initial range |
| --- | --- |
| Frequency | 10 Hz to 20 kHz |
| Parametric Q | 0.1 to 10 |
| Parametric gain | -18 dB to +12 dB |
| High-shelf gain | -12 dB to +12 dB |
| Pre-gain | -24 dB to 0 dB |
| Clip level | -12 dBFS to 0 dBFS |
| Headroom margin | 3 dB |

These values are product policy, not permanent restrictions of the reusable
library.

## Fixed-Point Program

Coefficient generation produces a complete immutable program suitable for
copying into the audio-owned runtime context:

```c
typedef struct {
    speaker_eq_channel_mode_t channel_mode;
    bool bypass;

    int32_t pregain_q27;
    int32_t clip_threshold;

    q2_30 coeffs[SPEAKER_EQ_SECTION_COUNT * 5];
    left_shift_t shifts[SPEAKER_EQ_SECTION_COUNT];

    float recommended_pregain_db;
} speaker_eq_program_t;
```

The exact layout may include explicit alignment attributes required by the
XMOS VPU implementation.

The runtime context contains:

- One active program.
- Two independently aligned 64-word cascade state arrays.
- No heap allocations.
- No mutexes, queues, tasks, or hidden global state.

## Public API

The planned API separates non-real-time design from real-time processing:

```c
speaker_eq_status_t speaker_eq_design_program(
    speaker_eq_program_t *program,
    const speaker_eq_config_t *config,
    const speaker_eq_limits_t *limits,
    uint32_t sample_rate_hz);

speaker_eq_status_t speaker_eq_init(
    speaker_eq_t *eq,
    const speaker_eq_program_t *initial_program);

speaker_eq_status_t speaker_eq_apply_program(
    speaker_eq_t *eq,
    const speaker_eq_program_t *program);

void speaker_eq_reset(speaker_eq_t *eq);

void speaker_eq_process_frame(
    speaker_eq_t *eq,
    int32_t *channels[SPEAKER_EQ_CHANNEL_COUNT],
    size_t frame_length);
```

Concurrency contract:

- `speaker_eq_design_program()` may run in a non-audio worker.
- `speaker_eq_apply_program()` is called only by the audio-stage owner at a
  frame boundary.
- `speaker_eq_process_frame()` and `speaker_eq_apply_program()` are never
  concurrent for the same context.
- The library does not provide internal synchronization.

## Processing Order

For every active channel, processing is:

```text
input
  -> saturating pre-gain
  -> eight-section biquad cascade
  -> output clip threshold
  -> output
```

Planned low-level calls:

- `adsp_dB_to_gain()` converts pre-gain to Q27.
- `adsp_fixed_gain()` applies pre-gain with saturation.
- `adsp_cascaded_biquads_8b()` processes the fixed cascade.
- `adsp_clipper()` applies the final threshold.

## Headroom And Overflow

`adsp_biquad()` does not guarantee saturation. An intermediate section can wrap
before the final clipper sees the result. The final clipper is therefore not a
replacement for sufficient pre-gain.

The initial safety strategy is:

1. Apply pre-gain before the first biquad.
2. Calculate conservative recommended headroom from enabled positive boosts.
3. Add the product-configured headroom margin.
4. Return `SPEAKER_EQ_INSUFFICIENT_HEADROOM` when policy requires enforcement
   and configured pre-gain is insufficient.
5. Exercise every intermediate section with near-full-scale test vectors.
6. Document that configurations outside the enforced profile can still cause
   fixed-point wraparound.

If XMOS adds a suitable saturating `lib_audio_dsp` biquad, the runtime can adopt
it without changing the public EQ configuration or device-control protocol.

## Runtime Configuration Updates

The first implementation uses frame-boundary replacement and state reset:

1. A non-audio context validates semantic settings.
2. It designs a complete inactive `speaker_eq_program_t`.
3. It publishes the complete program to the audio pipeline.
4. The audio stage checks for a pending program at the beginning of a frame.
5. The audio stage copies or swaps the program atomically from its own context.
6. Both channel-state arrays are cleared.
7. The frame is processed with only the new program.

This prevents partially updated coefficients but may create an audible click or
low-frequency transient. That behavior is accepted for the initial version.

The future transition model is a 20 ms crossfade between old and new complete
cascades. The program/runtime separation is intended to permit that extension
without changing semantic settings or the wire protocol.

## Compiled Speaker Preset

The reusable library does not contain product tuning. The serial pipeline owns
a compiled `speaker_eq_config_t` and validates it through the same API used for
runtime settings.

Required preset inputs are:

- Initial stereo-linked or mono mode.
- HPF mode and cutoff frequency.
- Enable, frequency, Q, and gain for all five parametric bands.
- High-shelf enable, frequency, Q, and gain.
- Pre-gain.
- Clip level.

The initial product preset is mono with a 70 Hz fourth-order Butterworth HPF,
the five measured peaking filters below, -8 dB pre-gain, 0 dBFS clipping, and
the high shelf disabled:

| Band | Frequency | Gain | Q |
| --- | --- | --- | --- |
| 1 | 133 Hz | -4.0 dB | 1.690 |
| 2 | 1944 Hz | -13.5 dB | 1.300 |
| 3 | 3557 Hz | -5.0 dB | 3.100 |
| 4 | 14603 Hz | -7.0 dB | 1.300 |
| 5 | 5500 Hz | +5.0 dB | 2.000 |

The disabled shelf retains candidate settings of 10 kHz, -3 dB, and Q 0.707
for later listening tests.

## Serial Pipeline Integration

The current speaker frame is planar stereo with 720 samples per channel. The EQ
stage will use the generic-pipeline callback signature `void (*)(void *)` and
process the frame in place.

The proposed stages are:

```text
stage 0:
    allocate frame
    receive and deinterleave I2S input
    apply pending EQ program at frame boundary
    process stereo or mono EQ

stage 1:
    pack processed frame
    transmit to the secondary stereo I2S output
    downsample the same processed signal for AEC reference
    queue AEC reference
    release frame
```

Placing EQ before `speaker_pipeline_output()` ensures the DAC output and AEC
reference contain the same post-EQ signal. In mono mode both output channels and
both AEC-reference channels contain the same processed mono sample.

The EQ implementation will not retain or free the generic-pipeline frame.

## Device-Control Integration

Device control will be added after the library and serial pipeline are working.

The planned flow is:

```text
SPI on tile 0
  -> synchronous device-control/intertile dispatch
  -> tile-1 EQ servicer callback
  -> copy decoded request into a bounded queue
  -> return "accepted"
  -> lower-priority EQ control worker
  -> validate and design complete program
  -> publish pending program
  -> audio-stage frame-boundary apply
  -> update applied generation
```

The callback must not:

- Retain the transport payload pointer.
- Generate coefficients.
- Reset audio state.
- Wait for a frame boundary.
- Access flash.
- Block on the audio stage.

A successful write means that a request was accepted, not necessarily that it
is already active. Status reads will expose requested generation, applied
generation, last asynchronous error, and pending state.

Adding the EQ servicer will require increasing the expected Satellite1
device-control servicer count from three to four.

### Wire-format principles

- Use a dedicated EQ schema version.
- Use explicit little-endian serialization.
- Do not transmit native C structs or floating-point values.
- Keep complete writes below the 253-byte SPI write-payload limit.
- Return complete configuration in one read where practical.
- Explicitly validate read/write direction in the EQ callback.

Suggested semantic encodings:

| Value | Wire representation |
| --- | --- |
| Frequency | `uint32_t` millihertz |
| Q | `uint16_t` Q multiplied by 1000 |
| Gain | `int16_t` millidecibels |
| Pre-gain | `int16_t` millidecibels |
| Clip level | `int16_t` millidecibels relative to full scale |
| Enable/mode | `uint8_t` enum |
| Generation | `uint32_t` |

Potential commands include:

- Set/get complete configuration.
- Set/get channel mode.
- Set/get bypass.
- Set/get each of the five parametric bands.
- Set/get HPF.
- Set/get high shelf.
- Set/get pre-gain and clip level.
- Get requested/applied status.
- Restore the compiled preset.

The resource ID and final command allocation remain to be selected.

## Future Active Crossover Pipeline

The future pipeline will produce two stereo branches:

- A stereo low-pass branch.
- A stereo high-pass branch.

It will reuse the low-pass/high-pass design functions from `fph::speaker_eq`.
Each branch and channel requires independent filter state.

Important crossover behavior:

- LR12 branches are each -6 dB at crossover and require polarity inversion of
  one branch for flat electrical summation.
- LR24 branches are each -6 dB at crossover and normally sum with matching
  polarity.
- A fourth-order Butterworth filter is not equivalent to LR24.
- Output port and four-channel I2S mapping must be defined before
  implementation.
- Mono behavior for the crossover pipeline will be specified in its README
  before implementation.
- Topology changes should eventually use the planned 20 ms crossfade.

## Verification Plan

### Coefficient design

- Verify every HPF and LPF mode at 48 kHz.
- Verify Butterworth cutoff is approximately -3 dB.
- Verify Linkwitz-Riley cutoff is approximately -6 dB.
- Verify LR12 complementary behavior with one branch inverted.
- Verify LR24 complementary summation without inversion.
- Compare responses against SciPy and XMOS Python references.
- Verify quantized pole stability.

### Parametric and shelf response

- Verify frequency, Q, and gain for all five peak slots.
- Verify high-shelf frequency, Q, and gain.
- Verify disabled filters produce bypass coefficients.
- Verify product-limit boundary values and rejection cases.

### Runtime behavior

- Verify zero input remains zero.
- Verify frame-split processing equals continuous processing.
- Verify state persists across frames.
- Verify stereo channels have independent state.
- Verify applying a program clears both state banks.
- Verify whole-EQ stereo bypass is bit-exact.
- Verify pre-gain and clipping behavior.
- Test near-full-scale signals at every intermediate section.

### Mono behavior

- Verify full-scale left plus full-scale right does not overflow the downmix.
- Verify opposite-polarity inputs cancel as expected.
- Verify odd sums use rounding toward zero.
- Verify both output channels are sample-identical.
- Verify only one EQ state bank advances.
- Verify mono bypass performs only averaging and duplication.
- Verify stereo/mono changes apply only at frame boundaries and reset state.

### Pipeline integration

- Verify the generic-pipeline callback types are exact.
- Verify the planar `[2][720]` layout is preserved.
- Verify EQ output reaches the secondary stereo I2S output.
- Verify the AEC reference is derived from post-EQ samples.
- Verify passthrough and serial-EQ implementations are separately selectable.
- Build both tile executables and the merged firmware image.
- Review tile-1 memory, stack, and timing reports.
- Run sustained 48 kHz playback while the voice pipeline is active.

### Device control

- Verify exact payload lengths and little-endian decoding.
- Verify invalid channel mode, band, filter type, frequency, Q, and gain.
- Verify queue-full behavior.
- Verify transport payloads are copied before callback return.
- Verify requested and applied generations.
- Verify reads during updates return consistent snapshots.
- Verify rapid writes cannot expose partial coefficients to the audio stage.

## Implementation Phases

### Phase 1: Reusable library

1. Add `modules/fph/speaker_eq` and its CMake target.
2. Define semantic configuration, limits, program, status, and runtime types.
3. Implement HPF and LPF design helpers.
4. Implement five peaking sections and one high shelf.
5. Implement program validation and conservative headroom reporting.
6. Implement stereo-linked and mono frame processing.
7. Implement frame-boundary program replacement with state reset.
8. Add xsim/Python response and fixed-point tests.

### Phase 2: Serial speaker pipeline

1. Add the `serial_eq` pipeline target and source.
2. Add the compiled product preset.
3. Initialize and validate the preset before pipeline tasks start.
4. Process EQ in the first generic-pipeline stage.
5. Preserve post-EQ DAC and AEC-reference behavior.
6. Build and inspect firmware resource reports.

### Phase 3: Device control

1. Allocate an EQ resource ID and command map.
2. Add the tile-1 servicer and control worker.
3. Define and test the versioned wire schema.
4. Add bounded request and prepared-program queues.
5. Add requested/applied generation status.
6. Add host-side command helpers and protocol documentation.

### Phase 4: Active crossover

1. Finalize branch-to-I2S output mapping.
2. Finalize crossover mono behavior.
3. Implement independent LPF and HPF branches.
4. Handle LR12 polarity inversion.
5. Add the 20 ms topology crossfade.

## Acceptance Criteria For The Initial Serial Pipeline

- The firmware builds with XTC 15.3.1 and the project Python environment.
- The serial pipeline supports stereo-linked and averaged-mono modes.
- The serial pipeline supports HPF bypass, Butterworth 12/24, and LR 12/24.
- Five peaking filters and one high shelf are independently configurable.
- The compiled preset passes the same validation as runtime settings.
- No coefficient generation occurs in the audio stage.
- Program changes occur only at frame boundaries and reset state.
- Mono processing is performed once and duplicated to both I2S channels.
- The AEC reference matches the post-EQ speaker output.
- Product limits and insufficient-headroom errors are enforced as configured.
- Frequency-response tests match the chosen references within defined
  fixed-point tolerance.
- Firmware memory and real-time constraints pass with documented headroom.

## Open Product Inputs

- EQ device-control resource ID.
- Final command IDs and host API naming.
- Future active-crossover I2S port/channel mapping.
- Future active-crossover mono behavior.
