# Satellite1 main-only 4Y2X on fwk_voice v0.9.0

This report describes the no-EQ implementation subsequently committed as
`0b92023232e2b33bbcbd5a42b23b1d0acb8b8ea5`. The uncommitted combined speaker-EQ
integration is reported separately in [the EQ report](4y2x-speaker-eq-v0.9.0.md).

## Scope and provenance

Implementation checkout:
`/Users/mischa/.local/share/opencode/worktree/20d933e7696444741ef981b7405dc73e4e2a8e29/satellite1-4y2x-main-only-v090`.
Branch: `experiment/satellite1-4y2x-main-only-v0.9.0`.
Unchanged HEAD: `f27d9383a1bd6442c4e0c2ccb07f5d3b70b1ac29`.
The checkout was clean; branch, HEAD and write readiness were checked before edits.
No commits, publication, hardware access or flashing were performed.

The base commit did not contain the v0.9.0 integration. The tracked binary diff
and all four new files were first captured and ported from the read-only sibling
`satellite1-4y1x-voice-v090`. The captured patch, status and new-file hashes are in
`build_evidence/4y1x-source{.patch,-status.txt,-provenance.json}`. The patch SHA256
is `3f54cd4901efb09b71598c286e705efc48965bacd086ee542a35423e912d3de6`.
The submodule revision is **74b9e2e2c4b747efe124f35a52e654e0a19b6c87**, fwk_voice
v0.9.0. The original migration report is retained at
`docs/4y1x-voice-v0.9.0.md` as historical baseline evidence, not candidate behavior.

The recovered source was read over SSH from
`siekmann@mbp-co2t83cngtf1.fritz.box`, archive
`/Users/siekmann/fph/from_tm/orbit_dev/experiments/recorded_audio_evaluation/.runs/aec-main-only-4y2x-014/`.
All 20 `implementation/firmware/` files, both patches, final provenance and
verification, frozen design, memory comparison, dev133/dev134 firmware evidence
and the parent `MAIN_ONLY_4Y2X_TRADEOFF.md` are copied under
`build_evidence/recovered/`, with byte counts and SHA256 in
`SHA256-manifest.json`. Large recorded-audio trees were not copied.

The frozen `conversation-capture/prepared/variant/firmware-source.patch` is
35,118 bytes, SHA256
`09b630c327c32890706ab5c879c2d9bd0a181af95c93efbfeb702fd44987369f`.
It targets old base `0950ec679d7f1ce669d06f2306a07d0d28e97342`, not v0.9.0.
The patch and saved implementation, not the old branch tip or broken temporary
worktree, were the implementation authority. Neither the archive nor any source
checkout was modified. Dependency initialization initially failed with GitHub
SSH authentication; a command-local HTTPS URL rewrite completed normal recursive
initialization. Python is 3.11.13, xmos-ai-tools 1.4.2, XTC 15.3.1.

## Signal path and API integration

- Four physical E/W/N/S microphones retain board mapping `{4,5,0,1}`, existing
  saturating 10x microphone gain, speaker passthrough and transport buffers.
- Two independent reference lanes enter AEC without mono mixing. All eight
  microphone/reference pairs retain ten 240-sample phases: 150 ms at 16 kHz.
- No shadow filter instance or pool exists in the main-only aggregated state.
  All AEC, IC and application consumers share 4Y2X, 10/0 phase counts and
  `AEC_LIB_MAX_PHASES=20`. Descriptor capacity is per coefficient row, not a
  shortened filter bank. Configuration rejects a different capacity.
- `SATELLITE1_FIXED_DELAY_AEC_4Y2X_MAIN_ONLY=ON` is the branch default; it is
  mutually exclusive with `SATELLITE1_FIXED_DELAY_AEC_4Y1X`. To build the latter,
  explicitly set main-only OFF and 4Y1X ON in a fresh build directory.
- Local v0.9.0-derived headers preserve the new aggregated/filter types and
  embedded pools. `aec_init_filters()` validates exactly `(NULL shadow state,
  NULL shadow pool, zero shadow phases)` or a complete valid shadow configuration;
  mixed inputs leave all state untouched. The aggregated main-only initializer
  uses the null contract. Processing guards shadow FFT, energy, output, adaptation
  and reset accesses, including a missing-shadow error-FFT dispatch that otherwise
  asserts in upstream code. The single-thread four-channel schedule is retained.
- The recovered `aec_main_only_control.c/.h` is adapted only to v0.9.0 filter/shared
  type names, includes and channel bounds. Its 100-frame initial bootstrap,
  34-frame restart, 100-frame ineffective-estimate recovery, five-useful-frame
  early exit, 4x near-end power-growth gate, mu 0.5 and 20-frame/1.5x amplification
  reset remain intact. Init/reset clear the one-owner controller. AEC bypass does
  not invoke it. This is a heuristic, not shadow-controller equivalence.
- The recovered output contract is **East/AEC0 and West/AEC1**. North/South remain
  internal AEC channels. Four-residual averaging is disabled only for main-only;
  East continues through NS/AGC and West retains the existing second output slot.
  IC/VNR processing remains bypassed, as in this v0.9.0 baseline. Its migrated
  continuous input VNR and new AGC metadata APIs are retained, not reverted.
  Reference activity/power now inspect both independent lanes.
- The exported frame consequently has two residual slots instead of four;
  reference and four raw-microphone slots are unchanged. Both tiles compile the
  same layout. The first tile-0 worker inherits its input-function stack allowance
  when the averaging worker is removed. Four-channel AEC scratch is static with
  one worker owner and never escapes into queued frames, as in the recovery.
- Zero static microphone delay remains required. No speaker EQ, transport buffer
  shrink, heap shrink, channel reduction or shortened filter is used to fit RAM.

The archived speaker single-worker option, heap configurability/116 KiB reduction
and diagnostic control protocol were reviewed but not imported: this candidate
fits with the original speaker workers and 128 KiB tile-1 heap. Those ancillary
old-framework files do not justify replacing newer integration files wholesale.

## Matched v0.9.0 memory comparison

The ported 4Y1X source was saved under `build_evidence/baseline-source/` before
4Y2X changes and rebuilt locally with this checkout's pinned dependencies and
Python environment. Baseline and candidate use XTC 15.3.1, `-Os -g`, Satellite1,
large application memory model, and identical reserved heaps. The FPH candidate
library/test also selects the large memory model: its >256 KiB test data exceeds
small-model addressing. No RAM reduction is hidden in a build flag.

Resources are from the **active tile in each individual tile XE**, not placeholder
notes in the merged image. All sizes below are bytes.

| Category | v0.9.0 4Y1X rebuild | v0.9.0 4Y2X main-only | Delta |
| --- | ---: | ---: | ---: |
| Tile 0 code | 74,404 | 74,260 | -144 |
| Tile 0 data | 284,964 | 284,956 | -8 |
| Tile 0 linker stack | 2,724 | 2,724 | 0 |
| Tile 0 total | 362,092 | 361,940 | -152 |
| Tile 0 free / 524,288 | 162,196 | 162,348 | +152 |
| Tile 1 code | 60,964 | 62,420 | +1,456 |
| Tile 1 data | 380,300 | 425,548 | +45,248 |
| Tile 1 linker stack | 3,668 | 3,668 | 0 |
| Tile 1 total | 444,932 | 491,636 | +46,704 |
| Tile 1 free / 524,288 | 79,356 | 32,652 | -46,704 |

The local 4Y1X rebuild has 104 bytes more tile-1 data than its source report's
444,828-byte total; the relocated baseline source embeds longer diagnostic paths.
Use the actual local rebuild above for the paired comparison. The linker reports
eight tile-1 threads with no spare threads and passes with caveats.

| Static context / pool | 4Y1X | 4Y2X main-only |
| --- | ---: | ---: |
| AEC aggregate, including embedded pools/alignment | 211,512 | 251,976 |
| Main pool type size | 138,564 | 247,592 |
| Shadow pool actually allocated | 62,192 | 0 |
| Main-only controller, outside aggregate | 0 | 136 |
| Four-channel static output scratch | 0 | 3,840 |
| IC context, initialized but processing bypassed | 59,560 | 59,560 |
| NS context | 9,440 | 9,440 |
| AGC context and metadata | 312 | 312 |

Pool rows are subsets of the aggregate, not additional allocations. The archived
251,968-byte context belongs to the old framework; this v0.9.0 context is 251,976.
The imported 4Y1X baseline retains upstream's 40-descriptor bound; the requested
main-only ABI uses 20. Its 40,464-byte context increase therefore includes descriptor
compaction, not just changing reference count or removing the shadow filter.
The small shared shadow-comparison metadata remains part of upstream shared
state; no shadow filter object or coefficient/error pool is instantiated.

Compiler-derived `nstackwords * 4` requirements: AEC 10,528 → 6,688; NS
7,536 → 7,536; AGC 2,512 → 2,512; bypassed IC 0 → 0; zero delay 0 → 0.
The 40-byte averaging function is absent in main-only. AEC's requested task stack
is 12,264 → 8,424 bytes including the 1,024-byte minimum, two 180-byte interrupt
allowances and unchanged 352-byte output-function requirement. Its 3,840-byte
scratch moved from stack to static storage; this is not a measured peak-memory
saving. These are linked compiler bounds, not live high-water marks.

Complete microphone-pipeline task requests, using the actual linked local
function symbols (not same-named speaker functions):

| Task | 4Y1X | Main-only 4Y2X |
| --- | ---: | ---: |
| Tile 1 delay/input | 1,776 | 1,768 |
| Tile 1 AEC/output | 12,264 | 8,424 |
| Tile 0 averaging/input | 1,760 | absent |
| Tile 0 bypassed IC (now input owner) | 1,204 | 1,720 |
| Tile 0 NS | 8,740 | 8,740 |
| Tile 0 AGC/output | 10,192 | 10,192 |

Frame objects are 9,628 → 7,708 bytes because only the recovered E/W residual
slots are exported; all four raw microphones and both references remain present.

Heaps remain **163,840 bytes on tile 0 and 131,072 bytes on tile 1**, already in
linker data. Tasks, frame buffers and queues consume these reservations; do not
add their allocations again to linked totals. Minimum-ever free heap, largest
free block, RTOS stack watermarks and frame deadlines remain unmeasured.

## Reproduction, version identity and validation

```sh
source /Users/mischa/Projects/FutureProofHomes/XMOS_XTC_15.3.1/SetEnv.sh
source .venv/bin/activate
cmake -S . -B build_candidate -G Ninja \
  --toolchain "$PWD/xmos_cmake_toolchain/xs3a.cmake" \
  -DPython3_EXECUTABLE="$VIRTUAL_ENV/bin/python" \
  -DFIXED_DELAY_ONLY=ON -DALLOW_DIRTY_VERSIONING=ON \
  -DUSE_DEV_TRACKING=OFF -DFPH_AEC_4Y_TESTS=ON \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build build_candidate --target satellite1_firmware_fixed_delay \
  create_flash_img_satellite1_firmware_fixed_delay \
  create_upgrade_img_satellite1_firmware_fixed_delay \
  fph_aec_4y_init_canary_test -j 8
xsim build_candidate/modules/fph/lib_aec_4y/fph_aec_4y_init_canary_test.xe
python -m pytest tests/test_versioning tests/test_package_firmware_deb.py -q
git diff --check
```

Dev tracking was inspected, not bypassed. Its supported implementation refuses
to allocate a unique counter/store dirty dev builds; its factory post-step also
assumes `build/` rather than `build_candidate/`. Tracking therefore remains OFF
with dirty versioning explicitly allowed. No commit or invented counter is used.
The displayed **v1.1.0-dev is nonunique**. Exact artifact SHA256 and content
manifests, not that version string, identify this candidate.

The XE, factory and upgrade targets pass. Host versioning/packaging tests report
**17 passed, 1 skipped** (Debian packaging needs unavailable `dpkg-deb`). Both mutually enabled profiles and phase capacity 19 are
rejected at configuration. The actual tile-0 translation unit compiles with IC
processing enabled in a separate validation object, without enabling IC in the
candidate. All 175 translation units belonging to the linked firmware/AEC/IC/test
targets have consistent AEC ABI definitions. Board, gain/routing, I2S buffers,
speaker and heap configuration sources are byte-identical to HEAD. The recovered
controller body is byte-identical after the two required v0.9.0 type renames.
All 57 recovered files covered by original provenance pins match those pins.

The locally rebuilt baseline passes its real-library xsim test: 32 serial and
scheduled frame executions, output hashes, canaries, pools and schedule coverage.
The retained 4Y1X profile also passes those 32 serial/scheduled executions using
the new FPH headers and frame implementation (`4y1x-compat-test.log`).

The candidate simulator passes 72 scheduled frames across full/left-muted/
right-muted reference inputs, plus an anti-phase-reference frame seeded with
different real filter banks. The latter has exactly zero mono mix but a nonzero
echo estimate on all four microphones, directly rejecting reference averaging.
Null-shadow mixed-argument rejection leaves state untouched; state canaries,
exact pool extents, complete schedule coverage, untouched shadow-output buffers,
filter/controller reset, bootstrap early exit, near-end gating and amplification
reset pass. The final run additionally passes quiet-reference freezing,
new-reference bootstrap, low-coherence restart and persistent-ineffectiveness
recovery; see `final-aec-test.log` and its simulator-binary SHA256 receipt.
The successful simulator XE is retained as `validated-aec-test.xe`. The final
rebuild after header documentation edits has identical allocated code/data,
addresses and sizes (`validated-loadable-sections.json`), despite debug/container
hash differences.

Exact artifacts (both builds display nonunique v1.1.0-dev):

```text
Baseline:
ac6e5f7efc18b01e345f4ec455564f4057d1f78af99055bdd45360de415b4a25  build_baseline/satellite1_firmware_fixed_delay.xe
c993548f4b93c7ff9630cbab26c62d98326f5dc88201e0aea2b63a49c7b7c463  build_baseline/satellite1_firmware_fixed_delay.factory.bin
19b3832b1c2c09feabe1adbee249f02a76c3848c883fe52225663ca09f90ab27  build_baseline/satellite1_firmware_fixed_delay.upgrade.bin

Main-only 4Y2X:
2904844867f8a45ace090e083aba13d574b111382ed27c3b3ae51e200b6168f0  build_candidate/satellite1_firmware_fixed_delay.xe
a6def636c28b7fa0a3b2fbedc34aeac39e0fe6a3c4acd1c643a91bf493e1c45e  build_candidate/satellite1_firmware_fixed_delay.factory.bin
6c2749565e845908883c4bac4d70c5855c6da958afc44e8597634afa38c85083  build_candidate/satellite1_firmware_fixed_delay.upgrade.bin
```

An explicit final relink reproduced factory/upgrade hashes and all resource
figures but changed the XE container hash; the table identifies the final XE.
The earlier receipt is retained as `artifact-hashes-before-relink.json`. No
byte-for-byte XE reproducibility claim is made.

Ignored local evidence includes build/configuration/simulator logs,
`artifact-hashes.json`, `memory-comparison.json`, active-tile ELF/resource/symbol
dumps, `collect-memory.py`, compiler-derived `layout-symbols.txt`,
`abi-audit.json`, `preservation-checks.json`, environment/dependency receipts and
the captured source/archive provenance. Simulator runs require several minutes;
initial 200-second runs timed out and are not counted as passes.

## Runtime limitations and inherited tradeoffs

No hardware was accessed. Simulator tests exercise the real AEC library/math,
not the full RTOS firmware or physical timing. Generated VNR function-pointer
stack-analysis warnings remain. Linking does not prove startup, scheduling,
runtime heap/stack margins, audio quality or output equivalence.

Optional native sanitizer validation did not run: the full Darwin project lacks
native VNR/xscope targets, and an isolated real-AEC/xmath test build stops on the
pinned xmath reference backend's Clang `-Werror` INT32_MAX-to-float conversion in
`src/arch/ref/misc.c:70`. Neither dependency code nor warning policy was changed
to conceal this. Logs and the isolated test CMake entry remain in local evidence;
no ASan/UBSan pass is claimed. XS3 compilation and simulator validation pass.

The archive's dev134 measurements (515,492-byte tile-1 image, 116 KiB heap,
11,984-byte minimum free heap, 49 tests, 40 stereo and 22 conversation scenes)
belong **only to the old-framework image**. They are not candidate test results.
The inherited controller has known 8.50/10.25 s single-channel confirmations,
mixed higher-threshold recovery and unresolved application-output TTS
hallucinations. No claim of equivalent acquisition or recognition is made.
Future authorized runtime validation must retain those failures, measure startup,
heap/stack watermarks and deadlines, and cover independent stereo, near-end,
double-talk, reference loss/restart and path changes with recorded comparisons.
