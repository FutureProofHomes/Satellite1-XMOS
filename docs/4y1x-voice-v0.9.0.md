# Satellite1 4Y1X fwk_voice v0.9.0 migration

Speaker EQ behavior, build instructions and its same-4Y1X memory comparison are
documented in [the speaker EQ guide](4y1x-voice-v0.9.0-eq.md).

## Scope and source

- Checkout: `/Users/mischa/.local/share/opencode/worktree/20d933e7696444741ef981b7405dc73e4e2a8e29/satellite1-4y1x-voice-v090`.
- Branch: `experiment/satellite1-4y1x-aec-residual-average`.
- Unchanged base HEAD: `f27d9383a1bd6442c4e0c2ccb07f5d3b70b1ac29`.
- Baseline voice: `e230d556f52d70bc3a09367c90bac35242351b59`.
- Candidate voice v0.9.0: `74b9e2e2c4b747efe124f35a52e654e0a19b6c87`.
- Read-only integration reference:
  `/Users/mischa/Projects/FutureProofHomes/.worktrees/satellite1-aec-v0.9.0`,
  branch `experiment/fixed-delay-fwk-voice-v0.9.0`, HEAD
  `bb411c71b153e6c973d65f70a935a48351bae62a`, with uncommitted migration.
  Its captured binary Git diff has SHA256
  `83d715ee993dee39b9617944d94d275248122c7812b2f260c413c985429262dd`.

The task checkout was clean at the base before setup. Its original 4Y1X firmware
was built and its symbols/resources captured **before** implementation edits.
SSH fetch/clone attempts failed intermittently even with the configured GitHub
key. Dependencies were populated from local Git object stores at the exact pinned
commits, not copied from dirty working files. No source/canonical checkout was
changed, and no commits, publication, hardware access or flashing were performed.

Only `satellite1_firmware_fixed_delay` is supported. Configuration rejects
`FIXED_DELAY_ONLY=OFF` and `ENABLE_ALL_FFVA_PIPELINES=ON`; legacy pipelines have
not migrated. Speaker processing remains passthrough; no speaker EQ is added.

## Preserved signal path

- Four physical microphones, mapping `{4, 5, 0, 1}`; existing saturating 10x
  microphone gain and channel routing are unchanged.
- Stereo reference input is averaged to one mono AEC reference, with int64
  accumulation and division by two.
- Four microphone AEC channels, one reference, ten main-filter phases, five
  shadow-filter phases, 240-sample frames and the existing fixed delay.
- On tile 0, all four AEC residuals are averaged using int64 accumulation and
  division by four **before** NS and AGC. The remaining residual channels and
  microphone passthrough data retain their existing routing.
- IC/VNR processing remains explicitly bypassed, as in this branch's baseline.
  Initialization and its static context remain present in both builds.

## Integration and intentional behavioral changes

The FPH AEC target exports `AEC_MAX_Y_CHANNELS=4`, `AEC_MAX_X_CHANNELS=1`, and
the phase bounds publicly. Firmware, FPH IC, all AEC translation units and tests
therefore share the same upstream v0.9.0 aggregated `aec_state_t` and embedded
pool layout. Obsolete copied public headers and application pool definitions
are removed. The previous state ABI reserved descriptor arrays for two reference
channels even though only one reference was processed; the new bound is one
throughout. This reduces descriptor overhead, **not** the four-channel signal
path or filter lengths.

`aec_process_frame()` is upstream code, with the FPH-owned
`aec_tdist_chans4_threads1` schedule. Each of the one-, two- and three-task groups
covers all four channel indices exactly once per task on thread zero; reference
tasks skip indices beyond the configured single reference. The default two-channel
schedule is not linked. The local `aec_impl.c` follows v0.9.0's filter/aggregate
types, retains the unconditional frequency-spectrum length assertion, and rejects
invalid initialization bounds before touching state. Embedded pools require
checking the individual phase limits, not only descriptor-array capacity.

The serial frame implementation is retained only as a test reference, not linked
into production firmware. See `modules/fph/lib_aec_4y/README.md` for API constraints.

The inactive IC path is migrated to `ic_process_frame()` and continuous **input**
VNR metadata, rather than the old Boolean threshold of **output** VNR. Its actual
tile-0 translation unit also compiles with the bypass disabled in a separate
validation object; this does not enable IC in the shipped candidate. With IC
bypassed, AGC still receives zero VNR from the zero-initialized frame metadata.
The separate unused VNR prediction object is removed; it had already been
optimized out of the baseline executable.

AGC now receives `ref_active_flag`, calculated on the delayed mono reference at
the upstream -60 dBFS amplitude threshold (0.001), along with existing reference
power and channel-zero AEC correlation. This and the upstream AGC/VNR/runtime
changes mean the full pipeline is not claimed to be output-equivalent to v0.8.
IC initialization status is checked. VNR links the combined `fwk_voice::vnr`
target. Candidate Python is 3.11.13 with AI tools 1.4.2; baseline used the existing
Python 3.10.18 / AI tools 1.3.1 environment.

## Same-4Y1X memory comparison

XTC 15.3.1, Ninja, Satellite1 board, `-Os -g -mcmodel=large`, unchanged heap
reservations. These are **not** the 2Y2X source experiment's memory numbers.
All values are bytes. Resources come from each individual tile executable's
active tile, not the misleading placeholder notes in the merged XE.

| Tile / category | Original 4Y1X | v0.9.0 4Y1X | Delta |
| --- | ---: | ---: | ---: |
| Tile 0 code | 77,684 | 74,404 | -3,280 |
| Tile 0 data | 286,876 | 284,964 | -1,912 |
| Tile 0 linker stack | 2,724 | 2,724 | 0 |
| **Tile 0 total used** | **367,284** | **362,092** | **-5,192** |
| Tile 0 free / 524,288 | 157,004 | 162,196 | +5,192 |
| Tile 1 code | 53,356 | 60,964 | +7,608 |
| Tile 1 data | 389,756 | 380,196 | -9,560 |
| Tile 1 linker stack | 3,668 | 3,668 | 0 |
| **Tile 1 total used** | **446,780** | **444,828** | **-1,952** |
| Tile 1 free / 524,288 | 77,508 | 79,460 | +1,952 |

Combined linked usage falls by 7,144 bytes, but RAM is tile-local. Tile 1 remains
the limiting tile, with an eight-thread static upper bound and no spare threads
in the linker report. Both firmware link constraint checks pass with caveats.

### Static contexts and pools

| Object | Original 4Y1X | v0.9.0 4Y1X | Delta |
| --- | ---: | ---: | ---: |
| AEC context, including both pools and alignment | 222,224 | 211,512 | -10,712 |
| Main AEC pool payload/type size | 138,564 | 138,564 | 0 |
| Shadow AEC pool payload/type size | 62,192 | 62,192 | 0 |
| IC context, including internal buffers/VNR state | 59,960 | 59,560 | -400 |
| Separate VNR prediction object, actually linked | 0 | 0 | 0 |
| NS context, including internal buffers | 9,440 | 9,440 | 0 |
| AGC context plus metadata | 272 | 312 | +40 |
| VNR tensor arena | 888 | 840 | -48 |

Pool rows are subsets of the AEC context, **not additional allocations**. Main
pool alignment may pad storage beyond its type size. Context symbols include
all internal IC/NS/AGC state; no additional application pool is allocated for
these stages. These selected symbols do not explain every linked byte.

### Compiler-derived task stack requirements

Each value below is the resolved function `nstackwords` symbol multiplied by four,
not a measurement of live stack use. Read the linked executable's symbols;
unresolved object-file expressions can display zero before linking.

| Stage | Original 4Y1X | v0.9.0 4Y1X | Delta |
| --- | ---: | ---: | ---: |
| AEC | 6,248 | 10,528 | **+4,280** |
| Four-residual averaging | 40 | 40 | 0 |
| IC/VNR, bypassed | 0 | 0 | 0 |
| NS | 7,536 | 7,536 | 0 |
| AGC | 2,568 | 2,512 | -56 |
| Static delay, configured to zero | 0 | 0 | 0 |

Task allocation expressions add `configMINIMAL_STACK_SIZE` (256 words), 45 words
of interrupt allowance per `RTOS_THREAD_STACK_SIZE()` invocation, and input/output
function requirements where applicable. AEC's unchanged output allowance is
352 bytes; its requested stack changes from 7,984 to 12,264 bytes. Tile 0's AGC
stack request falls by 56 bytes. These exclude task-control blocks and allocator
overhead. The per-frame heap object grows by four bytes for continuous VNR.

Heaps stay **163,840 bytes on tile 0** and **131,072 bytes on tile 1**. They are
already included in linker data. Task stacks, frame buffers, queues and other
runtime allocations consume these reservations and must **not** be added again
to linked totals. Thus tile 1 has more linker free memory but its reserved heap
must accommodate an additional 4,280-byte AEC stack request. Minimum-ever free
heap and task high-water marks remain unmeasured.

Generated VNR code retains function-pointer stack-analysis warnings. Static
stack figures and link success alone do not prove runtime stack safety.

## Build and evidence

With recursive dependencies initialized at their pinned revisions:

```sh
source /Users/mischa/Projects/FutureProofHomes/XMOS_XTC_15.3.1/SetEnv.sh
uv venv --python python3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt pytest
source .venv/bin/activate
cmake -S . -B build_candidate -G Ninja \
  --toolchain xmos_cmake_toolchain/xs3a.cmake \
  -DPython3_EXECUTABLE="$VIRTUAL_ENV/bin/python" \
  -DFIXED_DELAY_ONLY=ON -DALLOW_DIRTY_VERSIONING=ON \
  -DUSE_DEV_TRACKING=OFF -DFPH_AEC_4Y_TESTS=ON
cmake --build build_candidate --target satellite1_firmware_fixed_delay \
  create_flash_img_satellite1_firmware_fixed_delay \
  create_upgrade_img_satellite1_firmware_fixed_delay \
  fph_aec_4y_init_canary_test -j 8
xsim build_candidate/modules/fph/lib_aec_4y/fph_aec_4y_init_canary_test.xe
python -m pytest tests/test_versioning tests/test_package_firmware_deb.py -q
git diff --check
```

Activate the environment: upstream invokes bare `python` and `xcore-opt`.
Only this worktree's three generated v0.8 VNR model files were removed before
v0.9 configuration; otherwise upstream's recursive glob would compile stale
`modules/lib_vnr/src/inference/` sources against the new runtime.

Ignored local evidence directories:

- `build_baseline/`: original build/configure logs, original images,
  `resources-tile{0,1}.txt`, `symbols.txt`, `version.h`, `SHA256SUMS`.
- `build_candidate/`: clean `build.log`, successful `final-build.log`, individual
  tile resources, symbols, images, `version.h`, `SHA256SUMS`, Python test log,
  IC-enabled compile log, AEC simulator build and execution logs.
- `build_evidence/`: captured source integration diff, dependency setup logs,
  source/submodule provenance and final content manifest.

The clean baseline used `USE_DEV_TRACKING=ON` and is tracked locally as
`v1.1.0-dev.100`. The existing factory tracking command assumes `build/`, so its
post-step was completed explicitly with
`versioning.py --build-dir "$PWD/build_baseline" track satellite1_firmware_fixed_delay`.
No versioning code or canonical tracking directory was changed.

The candidate is uncommitted: existing versioning intentionally refuses to store
dirty dev builds or allocate them unique counters. `USE_DEV_TRACKING=OFF` and
`ALLOW_DIRTY_VERSIONING=ON` therefore produce **nonunique `v1.1.0-dev`**, not a
tracked release. Identify the exact candidate by the SHA256 hashes below and the
content manifest; the displayed version alone is insufficient. No commit is
authorized or needed for this local evidence.

### Exact artifact provenance

Paths are relative to this task checkout. SHA256 values identify the bytes;
candidate version strings are deliberately not presented as unique identifiers.

```text
Baseline v1.1.0-dev.100
e3484c298f7fee402a842083203969b421ca31e2a9b6a05bafd4c5382d55bffa  build_baseline/satellite1_firmware_fixed_delay.xe
07a4731215638534a966f61e58c27ff31f4a4a186814dc1867e08fd74034084f  build_baseline/satellite1_firmware_fixed_delay.factory.bin
04b57a22b6bbb2011b76c66dc605038fcfcfcf6e475ee0203aeb2334e62dc6c9  build_baseline/satellite1_firmware_fixed_delay.upgrade.bin

Candidate v1.1.0-dev (untracked/nonunique)
3f02af38a885e59c467ba057eb7376b7611a07000ad7535fbe2fff341f4215b5  build_candidate/satellite1_firmware_fixed_delay.xe
fbe70b481b400022fe33b07721bd241d159dc7d0ace04a9840711e700c83c0bf  build_candidate/satellite1_firmware_fixed_delay.factory.bin
567aec32f1d105e549e24aff3086621ba6d7828c0192138f88e0376dccc48dc9  build_candidate/satellite1_firmware_fixed_delay.upgrade.bin
```

## Validation status and runtime limits

The complete candidate executable, factory and upgrade image targets pass.
Python versioning/packaging tests: **17 passed, 1 skipped**. The actual pipeline's
IC-enabled translation unit compiles separately without diagnostics.

The AEC test passes in `xsim`: **32 frame executions** (16 serial-reference and
16 scheduled), comparing per-channel output hashes for all four microphones,
with and without shadow output, including a reference-interruption frame.
Initialization bounds, state canaries, exact main/shadow pool extents and complete
four-channel task coverage pass. Reported sizes are `state=211512`,
`main_pool=138564`, `shadow_pool=62192`. This tests the candidate's real AEC
objects and math library, not a mock implementation. The simulator execution log
is `build_candidate/aec-test.log`.

`git diff --check` passes. Preservation checks confirm byte-identical board
mapping, microphone gain/routing source, application configuration and speaker
passthrough source, and identical mono-reference mixing and four-residual
averaging function bodies against the original 4Y1X base. A compile-command
audit confirms the same 4Y1X/10/5 ABI definitions across all AEC, IC and firmware
compilation units. The read-only integration source's captured Git diff remains
unchanged.

Simulator validation concerns the real AEC implementation and its schedule, not
the complete RTOS firmware or hardware timing. Next runtime validation requires
an explicitly authorized target: startup, per-tile minimum free heap, per-task
stack high-water marks, frame deadlines, near-end speech, playback, double-talk,
reference interruption and recorded-audio comparison. Audio quality and full
pipeline output equivalence are not established by this build.
