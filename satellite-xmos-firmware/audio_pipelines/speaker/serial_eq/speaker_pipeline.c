// Copyright 2022-2026 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

#include <stdint.h>
#include <string.h>

#include <xcore/assert.h>

#include "FreeRTOS.h"
#include "generic_pipeline.h"
#include "task.h"

#include "app_conf.h"
#include "speaker_eq.h"
#include "speaker_eq_preset.h"
#include "speaker_pipeline.h"

#if appconfAUDIO_PIPELINE_FRAME_ADVANCE * appconfAUDIO_SPK_PL_SR_FACTOR != appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE
#error The speaker pipeline frame advance needs to match the speaker sample rate
#endif

#if appconfAUDIO_PIPELINE_CHANNELS != SPEAKER_EQ_CHANNEL_COUNT
#error The serial speaker EQ pipeline requires two input and output channels
#endif

typedef struct {
    int32_t samples[appconfAUDIO_PIPELINE_CHANNELS]
                   [appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE];
} frame_data_t;

static speaker_eq_t speaker_eq;

static void *audio_pipeline_input_i(void *input_app_data)
{
    frame_data_t *frame_data = pvPortMalloc(sizeof(*frame_data));
    xassert(frame_data != NULL);
    memset(frame_data, 0, sizeof(*frame_data));

    int32_t *channels[SPEAKER_EQ_CHANNEL_COUNT] = {
        frame_data->samples[0],
        frame_data->samples[1],
    };
    speaker_pipeline_input(input_app_data,
                           channels,
                           SPEAKER_EQ_CHANNEL_COUNT,
                           appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE);
    return frame_data;
}

static int audio_pipeline_output_i(frame_data_t *frame_data,
                                   void *output_app_data)
{
    int32_t *channels[SPEAKER_EQ_CHANNEL_COUNT] = {
        frame_data->samples[0],
        frame_data->samples[1],
    };
    return speaker_pipeline_output(output_app_data,
                                   channels,
                                   SPEAKER_EQ_CHANNEL_COUNT,
                                   appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE);
}

static void stage_speaker_eq(void *data)
{
    frame_data_t *frame_data = data;
    int32_t *channels[SPEAKER_EQ_CHANNEL_COUNT] = {
        frame_data->samples[0],
        frame_data->samples[1],
    };

    speaker_eq_process_frame(
        &speaker_eq, channels, appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE);
}

static void empty_stage(void *data)
{
    (void)data;
}

static void initialize_pipeline_stages(void)
{
    speaker_eq_program_t initial_program;
    speaker_eq_status_t status = speaker_eq_design_program(
        &initial_program,
        &speaker_eq_preset_config,
        &speaker_eq_preset_limits,
        appconfI2S_AUDIO_SAMPLE_RATE);
    xassert(status == SPEAKER_EQ_STATUS_OK);

    status = speaker_eq_init(&speaker_eq, &initial_program);
    xassert(status == SPEAKER_EQ_STATUS_OK);
}

void speaker_pipeline_init(void *input_app_data, void *output_app_data)
{
    const pipeline_stage_t stages[] = {
        stage_speaker_eq,
        empty_stage,
    };
    const configSTACK_DEPTH_TYPE stage_stack_sizes[] = {
        configMINIMAL_STACK_SIZE +
            RTOS_THREAD_STACK_SIZE(stage_speaker_eq) +
            RTOS_THREAD_STACK_SIZE(audio_pipeline_input_i),
        configMINIMAL_STACK_SIZE +
            RTOS_THREAD_STACK_SIZE(empty_stage) +
            RTOS_THREAD_STACK_SIZE(audio_pipeline_output_i),
    };

    initialize_pipeline_stages();

    generic_pipeline_init((pipeline_input_t)audio_pipeline_input_i,
                          (pipeline_output_t)audio_pipeline_output_i,
                          input_app_data,
                          output_app_data,
                          stages,
                          (const size_t *)stage_stack_sizes,
                          appconfAUDIO_PIPELINE_TASK_PRIORITY,
                          2);
}
