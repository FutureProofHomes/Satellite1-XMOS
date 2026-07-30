// Copyright 2020-2024 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

#ifndef AUDIO_RUNTIME_GAIN_H_
#define AUDIO_RUNTIME_GAIN_H_

#include <stddef.h>
#include <stdint.h>

void audio_runtime_apply_input_gains_q24(int32_t *samples,
                                         size_t frame_count,
                                         size_t ref_channel_count,
                                         size_t mic_channel_count,
                                         int32_t ref_gain_q24,
                                         int32_t mic_gain_q24);

#endif /* AUDIO_RUNTIME_GAIN_H_ */
