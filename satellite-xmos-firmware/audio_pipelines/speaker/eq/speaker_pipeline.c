/* STD headers */
#include <string.h>
#include <stdint.h>

/* FreeRTOS headers */
#include "FreeRTOS.h"
#include "task.h"

/* Library headers */
#include "generic_pipeline.h"

/* App headers */
#include "app_conf.h"
#include "speaker_pipeline.h"
#include "speaker_eq/speaker_eq.h"

#if appconfAUDIO_PIPELINE_FRAME_ADVANCE * appconfAUDIO_SPK_PL_SR_FACTOR != appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE
#error The speaker pipeline frame advance needs to be set according the sample rate of both pipelines
#endif

#if ON_TILE(SPEAKER_PIPELINE_TILE_NO) && !SPEAKER_EQ_ACTIVE
#error The EQ speaker pipeline needs appconfSPEAKER_EQ_ENABLED and device control on the speaker tile
#endif

typedef struct {
    int32_t samples[appconfAUDIO_SPK_CHANNELS][appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE];
    speaker_eq_frame_tag_t eq_tag;
} frame_data_t;

static void *audio_pipeline_input_i(void *input_app_data)
{
    frame_data_t *frame_data;

    frame_data = pvPortMalloc(sizeof(frame_data_t));
    memset(frame_data, 0x00, sizeof(frame_data_t));

    speaker_pipeline_input(input_app_data,
                       (int32_t **)frame_data->samples,
                       2,
                       appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE);

    return frame_data;
}

static int audio_pipeline_output_i(frame_data_t *frame_data,
                                   void *output_app_data)
{
    return speaker_pipeline_output(output_app_data,
                               (int32_t **)frame_data->samples,
                               2,
                               appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE);
}

static void eq_stage_ch0(frame_data_t *frame_data)
{
#if SPEAKER_EQ_ACTIVE
    speaker_eq_process_ch0(frame_data->samples[0], &frame_data->eq_tag);
#else
    (void)frame_data;
#endif
}

static void eq_stage_ch1(frame_data_t *frame_data)
{
#if SPEAKER_EQ_ACTIVE
    speaker_eq_process_ch1(frame_data->samples[1], &frame_data->eq_tag);
#else
    (void)frame_data;
#endif
}

void speaker_pipeline_init(
    void *input_app_data,
    void *output_app_data)
{
    const int stage_count = 2;

    const pipeline_stage_t stages[] = {
        (pipeline_stage_t)eq_stage_ch0,
        (pipeline_stage_t)eq_stage_ch1,
    };

    const configSTACK_DEPTH_TYPE stage_stack_sizes[] = {
        configMINIMAL_STACK_SIZE + RTOS_THREAD_STACK_SIZE(eq_stage_ch0) + RTOS_THREAD_STACK_SIZE(audio_pipeline_input_i),
        configMINIMAL_STACK_SIZE + RTOS_THREAD_STACK_SIZE(eq_stage_ch1) + RTOS_THREAD_STACK_SIZE(audio_pipeline_output_i),
    };

#if SPEAKER_EQ_ACTIVE
    speaker_eq_init();
    speaker_eq_servicer_start();
#endif

    generic_pipeline_init((pipeline_input_t)audio_pipeline_input_i,
                        (pipeline_output_t)audio_pipeline_output_i,
                        input_app_data,
                        output_app_data,
                        stages,
                        (const size_t*) stage_stack_sizes,
                        appconfAUDIO_PIPELINE_TASK_PRIORITY,
                        stage_count);
}
