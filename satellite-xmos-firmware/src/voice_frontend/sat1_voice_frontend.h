#pragma once
#include "sat1_voice_policy.h"
#include "xmath/xmath.h"

void sat1_voice_frontend_init(void);
void sat1_voice_frontend_analyze(int32_t samples[4][240],
    const int32_t reference[240], float_s32_t aec_correlation,
    int reference_active, sat1_voice_frame_t *metadata);
void sat1_voice_frontend_cleanup(int32_t samples[4][240],
    const sat1_voice_frame_t *metadata);
