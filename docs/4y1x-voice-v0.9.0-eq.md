# 4Y1X fwk_voice v0.9.0 with speaker EQ

## Dependencies

- No-EQ benchmark baseline: `8063449d058f325067a222010be270248dc6207e`.
- EQ implementation reference: `83c47beadfb4aab4fa563a868c59bb565a999f82`.
- Voice: v0.9.0, `74b9e2e2c4b747efe124f35a52e654e0a19b6c87`.
- Added lib_audio_dsp: v1.5.1,
  `1caa362ae47186e61aa7c82611aa7423ce91fb63`.

## Signal path and control interface

The stereo speaker pipeline runs the real lib_audio_dsp biquads, gain slew,
coefficient slew, crossfades and peak limiter at 48 kHz, 720 samples per frame.
Both existing speaker stages remain; channel 0 tags a frame with a coherent
coefficient bank and channel 1 uses the same bank. A lower-priority design task
range-checks and designs two host-configurable slots, with up to 14 filters and
16 biquad sections. Section-boundary headroom is checked against an 18 dB cap;
rejected designs leave the playing bank intact. Flat/disabled/unwritten profiles
bypass, transitions fade over 128 samples, and the processing watchdog can bypass
an overloaded bank. No new default tuning is applied: startup EQ is disabled.

The production resource-231 servicer is registered on tile 1, with the tile-0
SPI host expecting four servicers rather than three. It supports info/stats,
routing, slot writes and slot readback. Payload layout/limits are documented in
`docs/device-control-spi-protocol.md`; the 214-byte slot fits the SPI payload
limit.
GET_STATS remains **command 1, 48 bytes**: tile-1 minimum-ever free heap at byte
offset 32, current free heap at offset 36. The API provides tile-1 heap telemetry;
it does not expose task-stack measurements.

The microphone/AEC pipeline uses all four microphones,
mapping `{4,5,0,1}`, saturating 10x mic gain, mono reference mix, 10/5 filter
phases, 240-sample AEC frames, custom four-channel single-thread schedule,
aggregated state/pools, four-residual averaging, bypassed IC/VNR and migrated
AGC metadata. Speaker output routing down-samples the **post-EQ** DAC samples
for the AEC reference. The memory comparison below uses identical microphone
filters, heap reservations and audio payload sizes in both builds.

## Same-commit no-EQ versus EQ memory

Both builds use XTC 15.3.1, Python 3.11.13, xmos-ai-tools 1.4.2, Ninja, Satellite1,
the existing `-Os -g -mcmodel=large` firmware flags, identical channel/phase counts
and identical heap reservations. lib_audio_dsp uses its source integration's
`-O3` target option. The `build_noeq` baseline uses commit `8063449`; `build_eq`
uses the EQ implementation described here. Individual tile executables provide
the active-tile resource reports;
merged-XE placeholder notes are not used for memory accounting.

All values below are bytes.

| Tile/category | No EQ, committed v0.9.0 | With EQ | Delta |
| --- | ---: | ---: | ---: |
| Tile 0 code | 74,404 | 74,404 | 0 |
| Tile 0 data | 284,964 | 284,964 | 0 |
| Tile 0 linker stack | 2,724 | 2,724 | 0 |
| **Tile 0 total** | **362,092** | **362,092** | **0** |
| Tile 0 free / 524,288 | 162,196 | 162,196 | 0 |
| Tile 1 code | 60,964 | 72,804 | +11,840 |
| Tile 1 data | 380,196 | 389,292 | +9,096 |
| Tile 1 linker stack | 3,668 | 3,668 | 0 |
| **Tile 1 total** | **444,828** | **465,764** | **+20,936** |
| Tile 1 free / 524,288 | 79,460 | 58,524 | -20,936 |

Both firmware link constraint checks pass with caveats; generated VNR code still
has function-pointer stack-analysis warnings. Tile 1 remains the limiting tile
and retains an eight-thread static upper bound with no spare hardware threads.
EQ adds RTOS tasks on those cores, not additional hardware cores. Link success
does not establish schedulability or runtime memory safety.

### Static EQ storage on tile 1

| Symbol/group | Bytes |
| --- | ---: |
| Two channel contexts, including filter state/coefficients, fade buffers, limiter/gains/stats | 4,000 |
| Control parameters (`ctrl`) | 504 |
| Designed slots/analysis (`designs`) | 832 |
| Shared published bank | 392 |
| Two frame-bank copies | 784 |
| Design scratch sections | 896 |
| Design-task parameter copy | 244 |
| Servicer state/resource/command map | 48 |
| Remaining named EQ sequence/status/task-handle objects | 40 |
| **Named static EQ objects** | **7,740** |

These objects are already part of linker data; do not add them to the total
again. The 9,096-byte data delta also includes other library/alignment/constant
changes, so the named-object sum is not a complete attribution. AEC/IC/NS/AGC
contexts remain 211,512 / 59,560 / 9,440 / 312 bytes respectively.

### Task stacks and reserved heap

Resolved compiler `nstackwords * 4` values:

| Entry point | No EQ | With EQ |
| --- | ---: | ---: |
| Speaker channel-0 stage | 0 | 248 |
| Speaker channel-1 stage | 0 | 240 |
| Speaker input callback | 6,144 | 6,144 |
| Speaker output callback | 8,080 | 8,080 |
| EQ design task | absent | 368 |
| EQ servicer task, including callback group | absent | 708 |
| Existing tile-1 LED-ring servicer | 472 | 716 |
| AEC stage | 10,528 | 10,528 |

`configMINIMAL_STACK_SIZE=256` words adds 1,024 bytes where used;
`RTOS_THREAD_STACK_SIZE()` adds 45 interrupt words (180 bytes) per invocation.
Thus the two speaker task requests grow from 7,528 / 9,464 to 7,776 / 9,704
bytes, a combined +488. The new design task requests 1,572 bytes and the servicer
888 bytes. The tile-1 indirect callback group grows from 392 to 636 bytes and
also increases the existing LED-ring servicer's request from 652 to 896 bytes
(+244), even though its source is unchanged. **Known additional task-stack
requests total 3,192 bytes**, before
two additional task-control blocks and allocator/control-registration overhead.
The servicer uses its existing source policy of compiler-derived stack plus
interrupt allowance, without an extra minimal-stack allowance.
The tile-0 callback group and its active GPIO/DFU task requirements are unchanged;
tile-1 GPIO/DFU functions are compiled but those tasks are not started there.
The complete per-tile compiler-symbol delta audit is retained in
`build_eq/compiler-stack-deltas.json`; the startup-task and microphone-stage
requirements do not increase. Speaker initialization grows by eight compiler
stack bytes but remains below the unchanged startup-task requirement.

The real firmware stack-group check passes: read callback requires 108 words,
write callback 159 words, and `device_control_cb_fptr_grp` reserves 159 words.
This specifically verifies that the indirect callbacks are included in the
servicer's calculated requirement; it is not a runtime high-water measurement.

The speaker pipeline still has two stages and the same two-entry interstage
queue. Its allocated frame grows from 5,760 to 5,768 bytes for the per-frame
coefficient-bank tag. Queue depth and audio payload sizes are not reduced.
Live frame count, allocator overhead and control-service allocations remain
runtime-dependent.

Resource registration adds a one-entry pointer queue for the new tile-1 servicer
(4-byte queue payload plus its RTOS queue control block) and grows the tile-0
host's servicer-table payload from 24 to 32 bytes. Registration messages and
command payloads also use the existing allocator. These are runtime heap
allocations, not separate static reservations; queue/TCB/allocator overhead has
not been measured in a running firmware instance.

Reserved heaps remain **163,840 bytes on tile 0** and **131,072 on tile 1**.
They are already counted in linker data. The task stacks and live frames above
consume those reserved heaps; adding them again to linked totals would double
count. Neither the 58,524 bytes of linker free RAM nor the test harness's stubbed
heap values measure live free heap. Minimum-ever heap and stack high-water marks
remain unknown.

## Build, tests and timing limits

Set `XMOS_XTC_ROOT` to the XTC 15.3.1 installation directory and activate a
Python 3.11 virtual environment containing `xmos-ai-tools==1.4.2` and `pytest`.
The following commands reproduce the untracked validation configuration:

```sh
source "$XMOS_XTC_ROOT/SetEnv.sh"
source .venv/bin/activate
cmake -S . -B build_eq -G Ninja \
  --toolchain xmos_cmake_toolchain/xs3a.cmake \
  -DPython3_EXECUTABLE="$VIRTUAL_ENV/bin/python" \
  -DFIXED_DELAY_ONLY=ON -DALLOW_DIRTY_VERSIONING=ON \
  -DUSE_DEV_TRACKING=OFF -DFPH_AEC_4Y_TESTS=ON
cmake --build build_eq --target satellite1_firmware_fixed_delay \
  create_flash_img_satellite1_firmware_fixed_delay \
  create_upgrade_img_satellite1_firmware_fixed_delay \
  fph_aec_4y_init_canary_test -j 8
BUILD_DIR="$PWD/build_eq" sh satellite-xmos-firmware/test/speaker_eq/run.sh
BUILD_DIR="$PWD/build_eq" sh satellite-xmos-firmware/test/speaker_eq/check_stacks.sh
xsim build_eq/modules/fph/lib_aec_4y/fph_aec_4y_init_canary_test.xe
python -m pytest tests/test_versioning tests/test_package_firmware_deb.py -q
git diff HEAD --check
```

- Full no-EQ and EQ executable/factory/upgrade builds: passed.
- Real firmware servicer stack-group checks: passed, both callbacks on tile 1.
- Existing host versioning/packaging tests: **17 passed, 1 skipped**.
- Stress-generator offline smoke: deterministic, finite, normalized band-limited
  noise with 9 dB crest; bounded tone/kick functions. No speech synthesis,
  playback or hardware stress was run.
- AEC simulator regression: passed, 32 serial/scheduled frame executions covering
  all four outputs, reference interruption, bounds, schedule coverage, pool
  extents and canaries, with and without shadow output.
- Full EQ simulator suite: **passed**, `DONE failures=0`; independent
  double-precision Python model: **PASS**. Seven printed design/response cases
  and 15 tone measurements pass, including the 16-section profile, crossover
  types, coefficient/response tolerances, limiter ceiling/retargeting, crossfade
  and coefficient glide, bypass transitions, malformed/range-invalid payloads,
  rejected-design retention and unchanged GET_STATS heap-field offsets.
- `git diff HEAD --check`: passed. Production EQ sources match the source branch;
  protected microphone/voice/versioning sources remain unchanged from `8063449`.

The EQ test links the real engine/design code and lib_audio_dsp/math archives;
test-only RTOS stubs drive the design-task loop and supply fixed heap values.
It therefore tests DSP/protocol state-machine behavior, not actual RTOS
concurrency, SPI transport, startup registration or runtime heap usage.

The source EQ budget is 4,000 us per channel, watchdog threshold 8,000 us for
three frames, with a 15 ms speaker frame. The watchdog samples channel 1's previous
frame. The isolated 16-section benchmark reported **3,501 us last per channel**,
with an EWMA of 2,471 us (which includes earlier profiles); a full design took
**5,256 us**. The final steady processing measurement is only 499 us below the
4,000 us per-channel budget in this harness. These are simulated reference-timer
values, not wall-clock test duration or measured hardware timing.
Simulator benchmark results are not a full-system deadline guarantee:
microphone AEC, I/O, interrupts, design/control tasks and SMP contention still
need measurement together on explicitly authorized hardware. AEC audio quality,
near-end/double-talk behavior and EQ transitions during playback also remain
hardware validation tasks.

## Versions, artifacts and provenance

The comparison images use **nonunique `v1.1.0-dev`** with
`USE_DEV_TRACKING=OFF`. Identify these validation artifacts by their exact hashes,
not the displayed version. Normal dev tracking requires a clean source tree and
`USE_DEV_TRACKING=ON`; it does not allocate unique counters for dirty sources.

The no-EQ factory/upgrade binaries match the earlier validated migration images
byte for byte. Their XE hash differs because this fresh build embeds its own
debug/build paths. Artifact creation uses `xflash -o`, not a hardware flash.
The EQ factory image is 225,280 bytes; its upgrade image is 221,184 bytes.
Generated MD5 sidecars were also checked against both comparison builds' images.

SHA256:

```text
b89c5e5b66b4eca77232d771e13bf9d955f590219f2207c74448bf7f2024313d  build_noeq/satellite1_firmware_fixed_delay.xe
fbe70b481b400022fe33b07721bd241d159dc7d0ace04a9840711e700c83c0bf  build_noeq/satellite1_firmware_fixed_delay.factory.bin
567aec32f1d105e549e24aff3086621ba6d7828c0192138f88e0376dccc48dc9  build_noeq/satellite1_firmware_fixed_delay.upgrade.bin
fcc84011d1d35ef02e9fb6f9a35d7beffd67cf3ee4b4dd8a3ec182ee8325b5a3  build_eq/satellite1_firmware_fixed_delay.xe
a04a4d8ca0aab07b5b06bd98d638f95fc3f77ae3f343eea73e1a8b171946c2cb  build_eq/satellite1_firmware_fixed_delay.factory.bin
140f4239b62af048182a65972e559ec77ba9109a77938a39b5dfe091b3999924  build_eq/satellite1_firmware_fixed_delay.upgrade.bin
```

Ignored local evidence is retained in `build_noeq/` and `build_eq/`: build logs,
individual tile resource reports, linked symbols, version headers and
`SHA256SUMS`; EQ/AEC simulator logs, Python results, stack-check log, named-object
memory JSON and final source/artifact provenance manifest are in `build_eq/`.
The final manifest covers staged, unstaged and untracked task files and exact
dependency commits, not merely `git diff` of tracked files.
