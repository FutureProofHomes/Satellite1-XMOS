// Copyright 2024 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

#ifndef AUDIO_PIPELINE_DSP_H_
#define AUDIO_PIPELINE_DSP_H_

#include <stdint.h>
#include "app_conf.h"


/* Note: Changing the order here will effect the channel order for
 * audio_pipeline_input() and audio_pipeline_output()
 */
typedef struct {
    int32_t samples[appconfMIC_PIPELINE_PROC_CHANNELS][appconfAUDIO_PIPELINE_FRAME_ADVANCE];
    int32_t aec_reference_audio_samples[appconfMIC_PIPELINE_REF_CHANNELS][appconfAUDIO_PIPELINE_FRAME_ADVANCE];
    int32_t mic_samples_passthrough[appconfMIC_PIPELINE_INPUT_CHANNELS][appconfAUDIO_PIPELINE_FRAME_ADVANCE];
} frame_data_t;

#endif /* AUDIO_PIPELINE_DSP_H_ */
