// Copyright 2020-2024 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

#include "audio_runtime_gain.h"

#include <limits.h>

#define AUDIO_RUNTIME_Q30_UNITY ((int32_t) 0x40000000)

static int32_t sat_s32(int64_t value)
{
    if (value > INT32_MAX) {
        return INT32_MAX;
    }
    if (value < INT32_MIN) {
        return INT32_MIN;
    }
    return (int32_t) value;
}

static int32_t mul_q30(int32_t sample, int32_t gain_q30)
{
    int64_t prod = (int64_t) sample * gain_q30;

    prod = (prod + (1LL << 29)) >> 30;
    return sat_s32(prod);
}

static void apply_gain_to_channels(int32_t *samples,
                                   size_t frame_count,
                                   size_t channel_offset,
                                   size_t channel_count,
                                   int32_t gain_q30)
{
    if (gain_q30 == AUDIO_RUNTIME_Q30_UNITY || channel_count == 0) {
        return;
    }

    for (size_t ch = 0; ch < channel_count; ch++) {
        int32_t *channel_samples = samples + ((channel_offset + ch) * frame_count);
        for (size_t i = 0; i < frame_count; i++) {
            channel_samples[i] = mul_q30(channel_samples[i], gain_q30);
        }
    }
}

void audio_runtime_apply_input_gains_q30(int32_t *samples,
                                         size_t frame_count,
                                         size_t ref_channel_count,
                                         size_t mic_channel_count,
                                         int32_t ref_gain_q30,
                                         int32_t mic_gain_q30)
{
    if (samples == NULL || frame_count == 0) {
        return;
    }

    apply_gain_to_channels(samples,
                           frame_count,
                           0,
                           ref_channel_count,
                           ref_gain_q30);
    apply_gain_to_channels(samples,
                           frame_count,
                           ref_channel_count,
                           mic_channel_count,
                           mic_gain_q30);
}
