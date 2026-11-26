#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "beamforming/sat1_beamformer.h"

#define SAT1_VOICE_FRAME_SAMPLES 240
#define SAT1_VOICE_Q15_ONE 32768U
#define SAT1_VOICE_NEAR_SPEECH 1U
#define SAT1_VOICE_ECHO_ONLY 2U
#define SAT1_VOICE_DIRECTION_VALID 4U
#define SAT1_VOICE_UNSETTLED 8U

/* Raw calibration crosses the tile boundary; speech evidence belongs to the
 * same audio frame and must not be read from another pipeline task's state. */
typedef struct {
    sat1_beamformer_diagnostics_t calibration;
    uint16_t speech_q15;
    uint16_t echo_q15;
    uint8_t flags;
    uint8_t reserved[3];
} sat1_voice_frame_t;
_Static_assert(sizeof(sat1_voice_frame_t) == 48, "Voice metadata ABI");

#define SAT1_VOICE_DECIMATED_FRAME 60
#define SAT1_VOICE_CORRELATION_WINDOW 120
#define SAT1_VOICE_REFERENCE_LAGS 256
typedef struct {
    /* Four-sample boxcar, scaled by 2^12 before correlation. */
    int32_t reference[SAT1_VOICE_CORRELATION_WINDOW + SAT1_VOICE_REFERENCE_LAGS];
    int32_t microphone[SAT1_VOICE_CORRELATION_WINDOW];
    unsigned history_count;
    unsigned speech_hold;
    uint16_t echo_q15;
    uint16_t echo_lag_samples;
} sat1_voice_policy_t;

void sat1_voice_policy_reset(sat1_voice_policy_t *state);
uint8_t sat1_voice_policy_analyze(sat1_voice_policy_t *state,
    const int32_t microphone[240], const int32_t reference[240],
    uint16_t speech_q15, bool reference_active);

/* Use the IC-delayed primary for every bypass/mix path. During speech the
 * cancellation estimate's energy is limited to 1/16 of primary energy. */
void sat1_voice_protected_cleanup(const int32_t delayed_primary[240],
    const int32_t cancelled[240], int32_t output[240], uint8_t flags,
    uint16_t *residual_gain_q15);
