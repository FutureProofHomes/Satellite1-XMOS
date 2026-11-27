// Copyright 2022-2023 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

#ifndef SPEAKER_PIPELINE_H_
#define SPEAKER_PIPELINE_H_

#include <stdint.h>
#include "app_conf.h"

typedef struct {
    int32_t samples[appconfAUDIO_SPK_CHANNELS][appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE];
} speaker_pcm_t;

void speaker_pipeline_init(void);
void speaker_pipeline_input(speaker_pcm_t *pcm);
void speaker_pipeline_output(const speaker_pcm_t *pcm);

#endif /* SPEAKER_PIPELINE_H_ */
