// Copyright 2022-2023 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

#include "FreeRTOS.h"
#include "task.h"
#include "speaker_pipeline.h"

#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)

#if appconfAUDIO_PIPELINE_FRAME_ADVANCE * appconfAUDIO_SPK_PL_SR_FACTOR != appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE
#error The speaker pipeline frame advance needs to be set according the sample rate of both pipelines
#endif

_Static_assert(appconfAUDIO_SPK_CHANNELS == 2, "Speaker passthrough requires stereo PCM");

static void speaker_pipeline_task(void *arg)
{
    (void)arg;
    static _Alignas(8) speaker_pcm_t pcm;

    for (;;) {
        speaker_pipeline_input(&pcm);
        /* Output copies PCM into the DAC ring and into independent reference storage. */
        speaker_pipeline_output(&pcm);
        taskYIELD();
    }
}

void speaker_pipeline_init(void)
{
    BaseType_t status = xTaskCreate(
        speaker_pipeline_task, "speaker",
        configMINIMAL_STACK_SIZE + RTOS_THREAD_STACK_SIZE(speaker_pipeline_task),
        NULL, appconfAUDIO_PIPELINE_TASK_PRIORITY, NULL);
    configASSERT(status == pdPASS);
}
#endif
