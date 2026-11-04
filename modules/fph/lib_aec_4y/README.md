# FPH 4Y AEC Variant

This module provides FPH-owned four-microphone AEC profiles without modifying the
upstream `modules/voice/modules/lib_aec` module.

The API and aggregated state/pools follow fwk_voice v0.9.0. The FPH-owned public
`aec.h`, `aec_state.h` and `aec_defines.h` are derived from that pinned version.
The main-only profile exports 4 microphones, 2 independent references, 10 main
phases, zero shadow phases and 20 descriptors per microphone row. It removes the
shadow instance and pool from the aggregate, rather than allocating unused
storage. The alternative 4Y1X profile retains 10/5 main/shadow phases and its
v0.9.0 layout. ABI definitions propagate publicly to **every** consumer, including
IC; never override them in a consumer or link both AEC variants.

`aec_impl.c` is derived from XMOS `lib_aec` under the XMOS Public Licence. Its
initialization validation rejects null state
or schedule, non-single-thread schedules, zero/out-of-range channel counts and
out-of-range phase counts before touching state. The void API
leaves state unchanged on rejection; callers must validate successful
initialization before processing. In particular, embedded pools impose the
per-channel phase bounds, even if descriptor arrays could hold more phases.
The existing unconditional spectrum-length assertion is also retained.

`aec_init_filters()` exposes checked pool initialization: the only absent-shadow
contract is `(NULL state, NULL pool, 0 phases)`; mixed configurations are rejected
without touching state. The aggregate initializer uses that contract in main-only
mode. AEC processing and reset never dereference an absent shadow. The error FFT
dispatch also treats an absent shadow task as a no-op, not an assertion failure.

`aec_l2_impl.c` and `aec_priv_impl.c` remain upstream sources. The local scheduled
frame implementation adds null-shadow dispatch and main-only controller update.
`aec_tdist_chans4_threads1` covers all four microphone channels
in one thread; the two-channel upstream defaults are not suitable. Channel
bounds skip the unused microphone indices for reference-only tasks. Consumers
must link only `fph::aec_4y`, not upstream `fwk_voice::aec`, in the same executable
because both export the AEC API symbols. The controller has one owner, matching
the fixed-delay pipeline's single AEC worker. Init/reset clear its state. It
preserves active-reference bootstrap/restart, near-end power-growth gating and
persistent-amplification coefficient reset; it is not equivalent to a shadow
controller. See `docs/4y2x-main-only-v0.9.0.md` for provenance and runtime limits.

With XTC and the matching Python environment active, configure with
`-DFPH_AEC_4Y_TESTS=ON`, build `fph_aec_4y_init_canary_test`, and run
`xsim build_candidate/modules/fph/lib_aec_4y/fph_aec_4y_init_canary_test.xe`.
The main-only test checks null-shadow contracts, bounds, pool extents, canaries,
schedule coverage, processing/reset, independent-reference influence and controller
transitions. The 4Y1X profile retains its serial-reference hash comparisons; that
serial implementation is test-only.
