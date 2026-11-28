#include "FreeRTOS.h"
#include "task.h"
#include "rtos_macros.h"
#include "xassert.h"
#include "audio_pipeline.h"

#define CAPTURE_CHANNELS (appconfSPEAKER_CHANNELS + appconfAUDIO_PIPELINE_CHANNELS)

_Static_assert(appconfAUDIO_PIPELINE_CHANNELS == 4, "Expected four microphones");
_Static_assert(appconfAUDIO_PIPELINE_SAMPLE_RATE == 16000, "Expected 16 kHz PCM");
_Static_assert(appconfAUDIO_SPK_PL_SR_FACTOR == 1, "Expected native-rate playback");

/* One static block per tile. The shared input callback fills reference first,
 * then microphones. The USB exporter moves the reference to the end. */
static int32_t capture_block[CAPTURE_CHANNELS][appconfAUDIO_PIPELINE_FRAME_ADVANCE]
    __attribute__((aligned(8)));

static void capture_task(void *arg)
{
    (void)arg;
    for (;;) {
#if ON_TILE(MICARRAY_TILE_NO)
        audio_pipeline_input(NULL, (int32_t **)capture_block, CAPTURE_CHANNELS,
                             appconfAUDIO_PIPELINE_FRAME_ADVANCE);
        rtos_intertile_tx(intertile_ctx, appconfAUDIOPIPELINE_PORT,
                          capture_block, sizeof(capture_block));
#else
        size_t len = rtos_intertile_rx_len(intertile_ctx, appconfAUDIOPIPELINE_PORT,
                                         portMAX_DELAY);
        xassert(len == sizeof(capture_block));
        rtos_intertile_rx_data(intertile_ctx, capture_block, len);
        audio_pipeline_output(NULL, (int32_t **)capture_block, CAPTURE_CHANNELS,
                              appconfAUDIO_PIPELINE_FRAME_ADVANCE);
#endif
    }
}

void audio_pipeline_init(void *input_app_data, void *output_app_data)
{
    (void)input_app_data;
    (void)output_app_data;
    BaseType_t status = xTaskCreate(capture_task, "raw capture",
                                   RTOS_THREAD_STACK_SIZE(capture_task), NULL,
                                   appconfAUDIO_PIPELINE_TASK_PRIORITY, NULL);
    configASSERT(status == pdPASS);
}
