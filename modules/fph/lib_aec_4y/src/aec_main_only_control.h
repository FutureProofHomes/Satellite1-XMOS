#pragma once

#include <stdint.h>
#include "aec.h"

/* Frame counts use the 15 ms AEC frame period. */
#ifndef AEC_MAIN_ONLY_BOOTSTRAP_FRAMES
#define AEC_MAIN_ONLY_BOOTSTRAP_FRAMES 100
#endif
#ifndef AEC_MAIN_ONLY_RECOVERY_DELAY_FRAMES
#define AEC_MAIN_ONLY_RECOVERY_DELAY_FRAMES 100
#endif
#ifndef AEC_MAIN_ONLY_RECOVERY_FRAMES
#define AEC_MAIN_ONLY_RECOVERY_FRAMES 34
#endif
#ifndef AEC_MAIN_ONLY_BOOTSTRAP_MU_Q30
#define AEC_MAIN_ONLY_BOOTSTRAP_MU_Q30 536870912 /* 0.5 */
#endif
#define AEC_MAIN_ONLY_DIVERGENCE_FRAMES 20

typedef struct {
    uint32_t bootstrap_remaining[AEC_MAX_Y_CHANNELS];
    uint32_t frozen_frames[AEC_MAX_Y_CHANNELS];
    uint32_t divergence_frames[AEC_MAX_Y_CHANNELS];
    uint32_t coherent_frames[AEC_MAX_Y_CHANNELS];
    uint32_t bootstrap_events[AEC_MAX_Y_CHANNELS];
    uint32_t reset_events[AEC_MAX_Y_CHANNELS];
    float_s32_t learned_echo_ratio[AEC_MAX_Y_CHANNELS];
    uint32_t previous_reference_mask;
    uint32_t seen_reference_mask;
} aec_main_only_control_t;

void aec_main_only_control_reset(void);
void aec_main_only_control_update(aec_filter_state_t *main_state);
const aec_main_only_control_t *aec_main_only_control_stats(void);
