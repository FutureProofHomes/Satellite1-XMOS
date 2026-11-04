# FPH 4Y AEC Variant

This module provides the FPH-owned `4Y x 1X` AEC ABI without modifying the
upstream `modules/voice/modules/lib_aec` module.

The public API and aggregated state/pool headers come directly from fwk_voice
v0.9.0. The target publicly exports `AEC_MAX_Y_CHANNELS=4`,
`AEC_MAX_X_CHANNELS=1`, ten main phases and five shadow phases. These bounds must
match in **every** translation unit using AEC state, including the custom IC
target. Do not override them in a consumer.

`aec_impl.c` is derived from XMOS `lib_aec` under the XMOS Public Licence. Its
only behavioral difference from v0.9.0 is initialization validation: null state
or schedule, non-single-thread schedules, zero/out-of-range channel counts and
zero/out-of-range phase counts are rejected before touching state. The void API
leaves state unchanged on rejection; callers must validate successful
initialization before processing. In particular, embedded pools impose the
per-channel phase bounds, even if descriptor arrays could hold more phases.
The existing unconditional spectrum-length assertion is also retained.

The low-level implementation and `aec_process_frame()` are compiled unchanged
from upstream. `aec_tdist_chans4_threads1` covers all four microphone channels
in one thread; the two-channel upstream defaults are not suitable. Channel
bounds skip the unused microphone indices for reference-only tasks. Consumers
must link only `fph::aec_4y`, not upstream `fwk_voice::aec`, in the same executable
because both export the AEC API symbols.

With XTC and the matching Python environment active, configure with
`-DFPH_AEC_4Y_TESTS=ON`, build `fph_aec_4y_init_canary_test`, and run
`xsim build_candidate/modules/fph/lib_aec_4y/fph_aec_4y_init_canary_test.xe`.
The test checks init bounds, exact pool extents, canaries, schedule coverage and
all-channel output hashes against the serial implementation, with and without
shadow output. The serial implementation lives only in the test target.
