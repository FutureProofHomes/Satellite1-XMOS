// Copyright 2022-2023 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

/* STD headers */
#include <string.h>
#include <stdint.h>
#include <xcore/hwtimer.h>

/* FreeRTOS headers */
#include "FreeRTOS.h"
#include "task.h"
#include "timers.h"
#include "queue.h"
#include "stream_buffer.h"

/* Library headers */
#include "generic_pipeline.h"

/* App headers */
#include "app_conf.h"
#include "speaker_pipeline.h"

#if appconfAUDIO_PIPELINE_FRAME_ADVANCE * appconfAUDIO_SPK_PL_SR_FACTOR != appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE
#error The speaker pipeline frame advance needs to be set according the sample rate of both pipelines
#endif

/* Playback/reference transport is stereo regardless of microphone count. */
enum { SPEAKER_CHANNELS = 2 };

typedef struct {
    int32_t samples[SPEAKER_CHANNELS][appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE];
} frame_data_t;

static void *audio_pipeline_input_i(void *input_app_data)
{
    frame_data_t *frame_data;

    frame_data = pvPortMalloc(sizeof(frame_data_t));
    configASSERT(frame_data != NULL);
    memset(frame_data, 0x00, sizeof(frame_data_t));

    speaker_pipeline_input(input_app_data,
                       (int32_t **)frame_data->samples,
                       SPEAKER_CHANNELS,
                       appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE);

    return frame_data;
}

static int audio_pipeline_output_i(frame_data_t *frame_data,
                                   void *output_app_data)
{
    return speaker_pipeline_output(output_app_data,
                               (int32_t **)frame_data->samples,
                               SPEAKER_CHANNELS,
                               appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE);
}

static void passthrough_stage(void *frame_data)
{
    (void)frame_data;
}

static void initialize_pipeline_stages(void)
{
    ;
}

void speaker_pipeline_init(
    void *input_app_data,
    void *output_app_data)
{
    /* Input and output are already the complete passthrough operation. Two
     * no-op stages allow the generic queue to retain two stereo frames in
     * addition to the producer's and consumer's frames. Reference backpressure
     * can therefore raise live 48 kHz transport storage from 5,760 to 23,040
     * bytes. Keep one frame in flight and let I2S apply backpressure directly.
     */
    const int stage_count = 1;

    const pipeline_stage_t stages[] = {
        passthrough_stage,
    };

    const configSTACK_DEPTH_TYPE input_stack = RTOS_THREAD_STACK_SIZE(audio_pipeline_input_i);
    const configSTACK_DEPTH_TYPE output_stack = RTOS_THREAD_STACK_SIZE(audio_pipeline_output_i);
    const configSTACK_DEPTH_TYPE stage_stack_sizes[] = {
        configMINIMAL_STACK_SIZE + RTOS_THREAD_STACK_SIZE(passthrough_stage) +
            (input_stack > output_stack ? input_stack : output_stack),
    };

    initialize_pipeline_stages();

    generic_pipeline_init((pipeline_input_t)audio_pipeline_input_i,
                        (pipeline_output_t)audio_pipeline_output_i,
                        input_app_data,
                        output_app_data,
                        stages,
                        (const size_t*) stage_stack_sizes,
                        appconfAUDIO_PIPELINE_TASK_PRIORITY,
                        stage_count);
}
