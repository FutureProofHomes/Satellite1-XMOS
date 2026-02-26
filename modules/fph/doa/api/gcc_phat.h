// Copyright (c) 2026
// GCC-PHAT DOA estimator for 4-mic circular array using lib_xcore_math
//
// Designed for:
//   - 4 microphones
//   - 16 kHz
//   - 240 sample frame advance
//   - 256 FFT GCC-PHAT
//
// Input layout expected:
//
//   [240 mic0][240 mic1][240 mic2][240 mic3]
//
// Angle output:
//   radians
//   (atan2 convention)
//
// Dependencies:
//   lib_xcore_math
//

#ifndef DOA4_GCC_PHAT_H_
#define DOA4_GCC_PHAT_H_

#include <stdint.h>
#include "xcore_math.h"

#ifdef __cplusplus
extern "C" {
#endif

// ------------------------------------------------------------
// Configuration constants
// ------------------------------------------------------------

#define DOA4_NUM_MICS          (4)

#define DOA4_FRAME_ADVANCE     (240)
#define DOA4_FFT_LENGTH        (256)

#define DOA4_TAIL_SAMPLES \
    (DOA4_FFT_LENGTH - DOA4_FRAME_ADVANCE)

#define DOA4_SPEC_BINS \
    ((DOA4_FFT_LENGTH/2) + 1)

// Physical array geometry
#define DOA4_ARRAY_RADIUS_M    (0.0355f)  // 71mm diameter

// Sampling parameters
#define DOA4_SAMPLE_RATE_HZ    (16000.0f)
#define DOA4_SPEED_OF_SOUND    (343.0f)

// Maximum GCC lag search window.
// 71mm spacing @16kHz ≈ ±4 samples.
#define DOA4_MAX_LAG_SAMPLES   (4)


// ------------------------------------------------------------
// DOA estimator state
// ------------------------------------------------------------

typedef struct {

    // --- overlap tails (16 samples per mic)
    int32_t tail[DOA4_NUM_MICS][DOA4_TAIL_SAMPLES];

    // --- FFT time-domain buffers (256 samples)
    int32_t td[DOA4_NUM_MICS][DOA4_FFT_LENGTH];

    // --- spectra memory (unpacked mono FFT)
    complex_s32_t spec_mem
        [DOA4_NUM_MICS][DOA4_SPEC_BINS];

    bfp_complex_s32_t Spec[DOA4_NUM_MICS];

    // --- GCC scratch
    complex_s32_t z_mem[DOA4_SPEC_BINS];
    bfp_complex_s32_t Z;

    int32_t mag_mem[DOA4_SPEC_BINS];
    bfp_s32_t Mag;

    int32_t corr_mem[DOA4_FFT_LENGTH];
    bfp_s32_t Corr;

} doa4_state_t;


// ------------------------------------------------------------
// API
// ------------------------------------------------------------

/**
 * Initialise DOA estimator state.
 *
 * Must be called once before processing frames.
 */
void doa4_init(
        doa4_state_t *state);


/**
 * Process one frame of 4-mic audio.
 *
 * Input layout:
 *
 *   input[0..239]     = mic0
 *   input[240..479]   = mic1
 *   input[480..719]   = mic2
 *   input[720..959]   = mic3
 *
 * Parameters:
 *
 *   state   : estimator state
 *   input   : pointer to 960 int32 samples
 *   in_exp  : BFP exponent (eg Q1.31 = -31)
 *
 * Returns:
 *
 *   DOA angle in radians.
 *
 * Convention:
 *
 *   atan2(y,x)
 *
 *   depends on mic ordering (see implementation).
 */
float doa4_process_frame(
        doa4_state_t *state,
        const int32_t *input,
        exponent_t in_exp);


/**
 * Optional helper:
 * convert radians → degrees.
 */
static inline float doa4_rad_to_deg(float rad)
{
    return rad * (180.0f / 3.14159265358979323846f);
}


#ifdef __cplusplus
}
#endif

#endif // DOA4_GCC_PHAT_H_