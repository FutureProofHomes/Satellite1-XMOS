# Main-only 4Y2X v0.9.0 with speaker EQ

## Outcome and scope

The combined firmware **links without shrinking heaps, filters, buffers or
features**. Tile 1 uses **512,572 / 524,288 bytes**, leaving **11,716 bytes**
outside its unchanged 128 KiB reserved heap. This is a static fit, not proof of
startup heap safety, real-time deadlines or audio quality.

The reviewed AEC implementation was committed first as
`0b92023232e2b33bbcbd5a42b23b1d0acb8b8ea5`
(`Integrate main-only 4Y2X AEC with fwk_voice v0.9.0`). All EQ integration changes
are **uncommitted for review**; no subsequent commit, push, publication, hardware
access or flashing is authorized or performed.

- Branch: `experiment/satellite1-4y2x-main-only-v0.9.0`.
- Checkout:
  `/Users/mischa/.local/share/opencode/worktree/20d933e7696444741ef981b7405dc73e4e2a8e29/satellite1-4y2x-main-only-v090`.
- Writer session: `ses_e59d8f0b5ffeA2V7QC0tvI471Y`.
- Parent-prepared readiness epoch: clean base/HEAD at the AEC commit above,
  exact authorized EQ files and related reports. The administrative manifest was
  read and verified before EQ writes; it was not manufactured or reassigned by
  this worker. HEAD and writer ownership remain unchanged.

## Source and integration

EQ source is local `feature/speaker_eq_dsp_4y1x`, pinned to
**83c47beadfb4aab4fa563a868c59bb565a999f82**. Its EQ commits are `83ebb3e`,
`3ca81e8`, `4ffb69f`, `25be6a8`, `ef6959c`, `be54869`, `83c47be`.
The new `lib_audio_dsp` dependency is exactly **v1.5.1**, commit
**1caa362ae47186e61aa7c82611aa7423ce91fb63**. It was initialized normally in
this checkout using a command-local HTTPS rewrite for GitHub SSH URLs.

A selective source port was used rather than merging the entire branch: the
branch also carries unrelated explicit-version overrides in `versioning.py` and
firmware CMake. Those overrides were not imported. The exact imported patch,
hash and readiness proof are in `build_eq_evidence/source-provenance.json` and
`source-eq.patch`. No merge is left unresolved. Source checkouts and the IntelMac
archive were not modified.

The production path contains the real DSP library, EQ engine, asynchronous
design task, resource-231 servicer and two-stage stereo speaker pipeline.
`SATELLITE1_SPEAKER_EQ` selects EQ versus the existing passthrough target for
both tiles; disabled builds exclude the EQ implementation sources. Runtime EQ
starts disabled. The source branch's slots, 14-filter/16-section bounds,
headroom rejection, limiter, coefficient slew, crossfade, bank publication and
overload bypass are retained. Speaker-frame allocation checks for failure before
zeroing the frame.

The committed AEC implementation is untouched: four E/W/N/S microphones, two
independent references, ten main phases per pair (150 ms), no shadow instance or
pool, capacity 20 across all ABI consumers, recovered controller, upstream v0.9.0
aggregated APIs, and East/West downstream interface. The voice pin remains
**74b9e2e2c4b747efe124f35a52e654e0a19b6c87**. IC/VNR bypass and NS/AGC behavior
are unchanged. The existing speaker output callback sends the post-EQ stereo
samples to the DAC and down-samples those same independent lanes for AEC; no
reference averaging or reference-tap rerouting was added.

Only existing EQ heap telemetry is present: **resource 231, GET_STATS command 1,
48 bytes**, tile-1 minimum-ever free at offset **32** and current free at **36**.
There is no imported command 64, allocation trace hook, both-tile diagnostic
extension or stack-watermark telemetry. No heap or transport-buffer settings
changed, and no unrelated memory-diagnostics branch was integrated.

## Matched memory comparison

The clean AEC commit was built in `build_no_eq_commit/` before EQ edits. The
combined candidate is in `build_with_eq/`. Both use XTC **15.3.1**, Python
**3.11.13**, AI tools **1.4.2**, Ninja, Satellite1, the same fixed-delay AEC
profile, application `-Os -g -mcmodel=large`, and dev tracking OFF. The new DSP
library uses its source branch's `-O3`; unchanged components retain their flags.
Resources come from the active tile in each **individual tile XE**, not merged-XE
placeholder notes. All numbers below are bytes.

| Tile/category | No EQ, commit 0b92023 | With EQ | Delta |
| --- | ---: | ---: | ---: |
| Tile 0 code | 74,260 | 74,260 | 0 |
| Tile 0 data | 284,956 | 284,956 | 0 |
| Tile 0 linker stack | 2,724 | 2,724 | 0 |
| **Tile 0 total used** | **361,940** | **361,940** | **0** |
| Tile 0 free / 524,288 | 162,348 | 162,348 | 0 |
| Tile 1 code | 62,420 | 74,260 | +11,840 |
| Tile 1 data | 425,548 | 434,644 | +9,096 |
| Tile 1 linker stack | 3,668 | 3,668 | 0 |
| **Tile 1 total used** | **491,636** | **512,572** | **+20,936** |
| Tile 1 free / 524,288 | 32,652 | 11,716 | -20,936 |

Both link constraint reports pass with caveats. Tile 1 retains an eight-thread
static upper bound and no spare hardware threads. RTOS tasks are not additional
dedicated hardware threads; neither static bound establishes scheduling margin.

### State and pools

The AEC aggregate stays **251,976 bytes**, including its **247,592-byte main
pool**; controller **136 bytes** and AEC output scratch **3,840 bytes** are also
unchanged. No shadow state or pool was reintroduced.

New EQ-related linked state symbols sum to **7,740 bytes**, already included in
the tile-1 data row:

| State | Bytes |
| --- | ---: |
| Parameter/control state | 504 |
| Designed slots and analysis | 832 |
| Shared published bank plus two frame banks | 1,176 |
| Two channel processing states | 4,000 |
| Design section scratch plus parameter scratch | 1,140 |
| Servicer state, resource description and command map | 48 |
| Remaining counters, handles and publication fields | 40 |

Each channel state is 2,000 bytes and each designed bank is 392 bytes. Banks
within the rows above are not additional allocations. Symbol sums omit linker
padding and other new read-only/library data; they do not independently sum to
the whole 9,096-byte linked-data increase.

### Compiler-derived task stacks and runtime heap requests

Stack requests use resolved linked `nstackwords * 4`, the existing 1,024-byte
minimum where specified, and 180 bytes per `RTOS_THREAD_STACK_SIZE()` interrupt
allowance. These are compiler bounds, not measured high-water marks.

| Tile-1 task | No EQ request | EQ request | Delta |
| --- | ---: | ---: | ---: |
| Speaker stage 0 / input | 7,528 | 7,776 | +248 |
| Speaker stage 1 / output | 9,464 | 9,704 | +240 |
| EQ design task | absent | 1,572 | +1,572 |
| EQ servicer task | absent | 888 | +888 |
| Existing tile-1 LED servicer | 652 | 896 | +244 |
| AEC / output | 8,424 | 8,424 | 0 |

The EQ design function/task bound is 368 bytes; the servicer bound is 708 bytes.
Its callbacks require 432/636 bytes, covered by the 636-byte device-control
callback group. Those callback bytes are already inside the servicer bound:
they must not be added again. The source stack-check script validates this group
in the linked candidate image. The shared tile-1 callback group grows from
392 to 636 bytes, also growing the already-created LED servicer task by 244
requested bytes. Tile-0's callback group is unchanged. DFU/GPIO function bounds
also grow in the tile-1 ELF, but those servicer tasks are instantiated only on
tile 0, so they are not extra tile-1 heap allocations.

The extra requested task-stack payload is **3,192 bytes**. Compiler sizing of the
actual configured kernel gives **124 bytes per TCB** and **72 bytes per queue
control block**. Two new tasks add 248 TCB bytes; the EQ servicer queue requests
76 bytes including its one pointer slot. Known additional persistent tile-1
requests are thus **3,516 bytes**, plus **8 bytes per live speaker frame**
(5,760 → 5,768 bytes for the bank tag). With heap_4's eight-byte header/alignment,
the nominal persistent charged delta is **3,568 bytes**, before live-frame count,
transient traffic and fragmentation effects. The tile-0 servicer table grows
by one eight-byte entry. Registration has a nine-byte transient payload; command
messages have a 20-byte header plus their payload/read buffer. These are static
allocation-accounting observations, not a runtime peak measurement.

Heaps remain **163,840 bytes on tile 0** and **131,072 bytes on tile 1**, already
included in linker data. All task/frame/queue requests consume those reservations
and must **not** be added on top of linked totals. The 11,716 bytes outside the
reserved tile-1 heap are distinct from any free bytes inside it. Runtime heap
minima and allocation success have not been measured for this combination.

## Build and validation

```sh
source /Users/mischa/Projects/FutureProofHomes/XMOS_XTC_15.3.1/SetEnv.sh
source .venv/bin/activate
cmake -S . -B build_with_eq -G Ninja \
  --toolchain "$PWD/xmos_cmake_toolchain/xs3a.cmake" \
  -DPython3_EXECUTABLE="$VIRTUAL_ENV/bin/python" \
  -DFIXED_DELAY_ONLY=ON -DALLOW_DIRTY_VERSIONING=ON \
  -DUSE_DEV_TRACKING=OFF -DFPH_AEC_4Y_TESTS=ON \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DSATELLITE1_SPEAKER_EQ=ON
cmake --build build_with_eq --target satellite1_firmware_fixed_delay \
  create_flash_img_satellite1_firmware_fixed_delay \
  create_upgrade_img_satellite1_firmware_fixed_delay \
  fph_aec_4y_init_canary_test -j 8
BUILD_DIR="$PWD/build_with_eq" sh satellite-xmos-firmware/test/speaker_eq/run.sh
BUILD_DIR="$PWD/build_with_eq" sh satellite-xmos-firmware/test/speaker_eq/check_stacks.sh
xsim build_with_eq/modules/fph/lib_aec_4y/fph_aec_4y_init_canary_test.xe
python -m pytest tests/test_versioning tests/test_package_firmware_deb.py -q -rs
git diff --check
```

XE, factory and upgrade image targets pass. The servicer stack-group check passes
for both callbacks (108/159 words, reserved group 159 words). Host tests report
**17 passed, 1 skipped**; Debian packaging requires unavailable `dpkg-deb`.
An offline 0.1-second generator smoke checks 48 kHz, stereo, 16-bit PCM with
identical channels; it invokes neither spoken labels nor playback. All **181**
firmware/AEC/IC/test translation units retain the same AEC ABI definitions.
Component simulator results:

- EQ xsim finishes with **`DONE failures=0`** and the Python reference checker
  reports **PASS**: seven accepted design/transition cases and fifteen tone
  comparisons, plus C checks for payload validation, rejected-bank preservation,
  bit-exact disabled/flat bypass, profile readback, limiter behavior, glide,
  crossfade and no-op-routing publication behavior. Watchdog trip/recovery is
  not forced by this fixture. The existing GET_STATS heap offsets
  are checked against test-stub values, not measured hardware heap values.
- 4Y2X AEC xsim passes **72 scheduled frames plus one anti-phase-reference frame**
  (73 total), null-shadow init/process/reset, bounds/canaries, four-channel
  scheduling, separate reference influence and controller transitions. State,
  main pool and controller remain 251,976 / 247,592 / 136 bytes.
- The retained 4Y1X ABI regression passes **32 serial/scheduled frame executions**,
  output hashes, pool/canary checks and schedule coverage. This is a component
  regression in this checkout, not a claim about the other 4Y1X session's build.
- The explicit EQ-OFF negative control builds successfully and restores the
  exact no-EQ resource figures (including tile 1 at 491,636 bytes). It was not
  used to obtain the combined EQ fit.
- `git diff HEAD --check` passes. Protected AEC/routing/gain/buffer/heap/versioning
  sources and the voice pin remain unchanged from the approved AEC commit.

The isolated xsim fixture reports 16-section channel times of 3,501 us last /
2,471 us average and a 5,256 us design run. These are simulator observations
without concurrent AEC/RTOS load, not hardware timing or deadline guarantees.

The EQ simulator compiles the actual engine/design and DSP/math archives, with
test-only RTOS stubs. Those stubs do not replace production integration. The
test does not simulate complete RTOS scheduling, SPI hardware or physical audio.
The native-sanitizer limitations in the no-EQ report remain: no new native
ASan/UBSan pass is claimed.

### Review observations

No conversational/history comments, proof/demo production identifiers or
fixture/scaffold production substitutes were found in the imported EQ engine,
design or servicer. Compiler-workaround, headroom and synchronization comments
are technical safety rationale and were retained. The **test-only**
`make_amp_ladder.py` module docstring includes historical amp/OCP observations
and stress-fixture recipes; those are retained fixture context, not measurements
or safety guarantees for this combined firmware. No amplifier stress test ran.

### Version and artifact identity

Both builds display **nonunique `v1.1.0-dev`** with tracking OFF. Supported
tracking will not allocate/store a unique dirty dev build, and an EQ commit is
not approved. No counter or explicit-version override was invented. Exact bytes
are identified by artifact SHA256 and the captured source/dependency manifests.

```text
No EQ (clean approved AEC commit):
69871aebee102e4174aff58b01bde9bc30ab0f0be901b95251e1a8622b4d5239  build_no_eq_commit/satellite1_firmware_fixed_delay.xe
a6def636c28b7fa0a3b2fbedc34aeac39e0fe6a3c4acd1c643a91bf493e1c45e  build_no_eq_commit/satellite1_firmware_fixed_delay.factory.bin
6c2749565e845908883c4bac4d70c5855c6da958afc44e8597634afa38c85083  build_no_eq_commit/satellite1_firmware_fixed_delay.upgrade.bin

Main-only 4Y2X + EQ (uncommitted):
1fb27fabc5613eda5fad151b76d605b2b1d9a6d36bcc9ec7763dba7fc4223277  build_with_eq/satellite1_firmware_fixed_delay.xe
49ef1bb7534a2d06ab544e7e4a7b11e3e020c4e709f6e7178381c051b4bf5da6  build_with_eq/satellite1_firmware_fixed_delay.factory.bin
9952affe163af045081a84f0789e63ecab91a4e79485056f87a5b0fa0956ab24  build_with_eq/satellite1_firmware_fixed_delay.upgrade.bin
```

The no-EQ factory/upgrade bytes match the previously reviewed AEC artifacts.
XE containers can differ on relink; use the exact hashes, not a bit-for-bit XE
reproducibility assumption. `build_eq_evidence/artifact-hashes.json` also pins
simulator executables and the tiny offline generator smoke artifact.

Other ignored local receipts include `memory-comparison.json`,
`collect-memory.py`, active-tile ELF/resource/symbol dumps, compiler-layout
sources/objects/results, `preservation-and-abi.json`, dependency/source provenance,
the complete EQ patch including new files, final source manifest, build logs,
`eq-tests.log`, `4y2x-aec-test.log`, `4y1x-aec-test.log`, `servicer-stacks.log` and
`host-tests.log`. Git's normal submodule initialization stages its new metadata
and gitlink; other EQ changes remain unstaged/untracked. None are committed.

## Runtime limitations

The link fit leaves only 11,716 bytes outside the reserved tile-1 heap. It is not
a measured worst-case startup or steady-state margin. No hardware was accessed;
startup, runtime free heap, RTOS stack safety, concurrency under load, speaker/AEC
deadlines, clipping/limiter behavior on the real amplifier and audio quality all
remain unvalidated. Existing resource-231 heap telemetry is the only retained
heap observation interface for future explicitly authorized runs.

The main-only controller's previously documented acquisition/recovery and TTS
recognition limitations are not resolved or requalified by adding EQ. Old
archive hardware campaigns and heap minima are not evidence for this candidate.
