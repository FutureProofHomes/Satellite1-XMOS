// Copyright 2022-2024 XMOS LIMITED.
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
#include "rtos_osal.h"

/* Library headers */
#include "generic_pipeline.h"

/* App headers */
#include "app_conf.h"
#include "audio_pipeline.h"
#include "audio_pipeline_dsp.h"
#include "audio_pipeline_control/audio_pipeline_control_settings.h"

#if appconfAUDIO_PIPELINE_FRAME_ADVANCE != 240
#error This pipeline is only configured for 240 frame advance
#endif

#if ON_TILE(1)
#if appconfINPUT_SAMPLES_MIC_DELAY_MS != 0
static stage_delay_ctx_t DWORD_ALIGNED delay_buf_state = {};
#endif
static aec_ctx_t DWORD_ALIGNED aec_state = {};

#define AUDIO_PIPELINE_FRAME_POOL_DEPTH 3

static frame_data_t DWORD_ALIGNED frame_pool[AUDIO_PIPELINE_FRAME_POOL_DEPTH];
static rtos_osal_queue_t frame_free_queue_ctx;
static rtos_osal_queue_t *frame_free_queue;

#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEBUG_SNAPSHOTS
audio_pipeline_debug_counters_t audio_pipeline_tile1_debug = {
    .magic = 0x54314442, /* T1DB */
};
#endif

#define AUDIO_PIPELINE_DSP_SAMPLE_LIMIT ((int32_t)0x00400000)

static int32_t clamp_dsp_input_sample(int32_t sample)
{
    if (sample > AUDIO_PIPELINE_DSP_SAMPLE_LIMIT) {
        return AUDIO_PIPELINE_DSP_SAMPLE_LIMIT;
    }
    if (sample < -AUDIO_PIPELINE_DSP_SAMPLE_LIMIT) {
        return -AUDIO_PIPELINE_DSP_SAMPLE_LIMIT;
    }
    return sample;
}

static void copy_mic_passthrough_to_processing(frame_data_t *frame_data)
{
    memcpy(frame_data->samples,
           frame_data->mic_samples_passthrough,
           sizeof(frame_data->samples));

    for (size_t ch = 0; ch < appconfMIC_PIPELINE_PROC_CHANNELS; ch++) {
        for (size_t frame = 0; frame < appconfAUDIO_PIPELINE_FRAME_ADVANCE; frame++) {
            frame_data->samples[ch][frame] =
                clamp_dsp_input_sample(frame_data->samples[ch][frame]);
        }
    }
}


static void *audio_pipeline_input_i(void *input_app_data)
{
    frame_data_t *frame_data;
#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEBUG_SNAPSHOTS
    audio_pipeline_tile1_debug.input_enter++;
    audio_pipeline_tile1_debug.rx_len_before++; /* before pool acquire */
#endif
    xassert(rtos_osal_queue_receive(frame_free_queue,
                                    &frame_data,
                                    RTOS_OSAL_WAIT_FOREVER) == RTOS_OSAL_SUCCESS);
#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEBUG_SNAPSHOTS
    audio_pipeline_tile1_debug.rx_len_after++; /* after pool acquire */
    audio_pipeline_tile1_debug.last_rx_len = (uint32_t) sizeof(frame_data_t);
#endif
    memset(frame_data, 0x00, sizeof(frame_data_t));

#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEBUG_SNAPSHOTS
    audio_pipeline_tile1_debug.rx_data_after++; /* before audio_pipeline_input */
#endif
    audio_pipeline_input(input_app_data,
                       (int32_t *) frame_data->aec_reference_audio_samples,
                       appconfMIC_PIPELINE_REF_CHANNELS + appconfMIC_PIPELINE_INPUT_CHANNELS,
                       appconfAUDIO_PIPELINE_FRAME_ADVANCE);
#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEBUG_SNAPSHOTS
    audio_pipeline_tile1_debug.input_return++;
#endif

    frame_data->vnr_pred_flag = 0;

    copy_mic_passthrough_to_processing(frame_data);
#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEBUG_SNAPSHOTS
    audio_pipeline_tile1_debug.output_after++; /* input wrapper completed */
#endif

    return frame_data;
}

static int audio_pipeline_output_i(frame_data_t *frame_data,
                                   void *output_app_data)
{

#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEBUG_SNAPSHOTS
    audio_pipeline_tile1_debug.output_enter++;
    audio_pipeline_tile1_debug.tx_before++;
#endif
    rtos_intertile_tx(intertile_ctx,
                      appconfAUDIOPIPELINE_PORT,
                      frame_data,
                      sizeof(frame_data_t));
#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEBUG_SNAPSHOTS
    audio_pipeline_tile1_debug.tx_after++;
#endif
    xassert(rtos_osal_queue_send(frame_free_queue,
                                 &frame_data,
                                 RTOS_OSAL_WAIT_FOREVER) == RTOS_OSAL_SUCCESS);

    return AUDIO_PIPELINE_DONT_FREE_FRAME;
}

static void stage_delay(frame_data_t *frame_data)
{
#if appconfAUDIO_PIPELINE_SKIP_STATIC_DELAY
#else
#if (appconfINPUT_SAMPLES_MIC_DELAY_MS > 0) /* Delay mics */
    size_t bytes_sent = xStreamBufferSend(
                                delay_buf_state.delay_buf,
                                &frame_data->samples,
                                AP_INPUT_SAMPLES_MIC_DELAY_CUR_FRAME_BYTES,
                                0);

    configASSERT(bytes_sent == AP_INPUT_SAMPLES_MIC_DELAY_CUR_FRAME_BYTES);

    if (xStreamBufferBytesAvailable(delay_buf_state.delay_buf) > AP_INPUT_SAMPLES_MIC_DELAY_BUF_SIZE_BYTES) {
        size_t bytes_rx = xStreamBufferReceive(
                                    delay_buf_state.delay_buf,
                                    &frame_data->samples,
                                    AP_INPUT_SAMPLES_MIC_DELAY_CUR_FRAME_BYTES,
                                    0);

        configASSERT(bytes_rx == AP_INPUT_SAMPLES_MIC_DELAY_CUR_FRAME_BYTES);
    }
#elif (appconfINPUT_SAMPLES_MIC_DELAY_MS < 0) /* Delay Ref*/
    size_t bytes_sent = xStreamBufferSend(
                                delay_buf_state.delay_buf,
                                &frame_data->aec_reference_audio_samples,
                                AP_INPUT_SAMPLES_MIC_DELAY_CUR_FRAME_BYTES,
                                0);

    configASSERT(bytes_sent == AP_INPUT_SAMPLES_MIC_DELAY_CUR_FRAME_BYTES);

    if (xStreamBufferBytesAvailable(delay_buf_state.delay_buf) > AP_INPUT_SAMPLES_MIC_DELAY_BUF_SIZE_BYTES) {
        size_t bytes_rx = xStreamBufferReceive(
                                    delay_buf_state.delay_buf,
                                    &frame_data->aec_reference_audio_samples,
                                    AP_INPUT_SAMPLES_MIC_DELAY_CUR_FRAME_BYTES,
                                    0);

        configASSERT(bytes_rx == AP_INPUT_SAMPLES_MIC_DELAY_CUR_FRAME_BYTES);
    }
#else /* Delay None */
#endif
#endif /* appconfAUDIO_PIPELINE_SKIP_DELAY */
}

static void stage_aec(frame_data_t *frame_data)
{
#if appconfAUDIO_PIPELINE_SKIP_AEC
#else
    int32_t DWORD_ALIGNED stage1_output[AEC_MAX_Y_CHANNELS][appconfAUDIO_PIPELINE_FRAME_ADVANCE];

    aec_process_frame_1thread(
            &aec_state.aec_main_state,
            &aec_state.aec_shadow_state,
            stage1_output,
            NULL,
            frame_data->samples,
            frame_data->aec_reference_audio_samples);

    frame_data->max_ref_energy = aec_calc_max_input_energy(
                                    frame_data->aec_reference_audio_samples,
                                    aec_state.aec_main_state.shared_state->num_x_channels);
    frame_data->aec_corr_factor = aec_calc_corr_factor(&aec_state.aec_main_state, 0);
    memcpy(frame_data->samples, stage1_output, AEC_MAX_Y_CHANNELS * appconfAUDIO_PIPELINE_FRAME_ADVANCE * sizeof(int32_t));
#endif
}

static void initialize_pipeline_stages(void)
{
    void *frame_data;

    xassert(rtos_osal_queue_create(&frame_free_queue_ctx,
                                   NULL,
                                   AUDIO_PIPELINE_FRAME_POOL_DEPTH,
                                   sizeof(void *)) == RTOS_OSAL_SUCCESS);
    frame_free_queue = &frame_free_queue_ctx;
    for (size_t i = 0; i < AUDIO_PIPELINE_FRAME_POOL_DEPTH; i++) {
        frame_data = &frame_pool[i];
        xassert(rtos_osal_queue_send(frame_free_queue,
                                     &frame_data,
                                     RTOS_OSAL_NO_WAIT) == RTOS_OSAL_SUCCESS);
    }

#if (appconfINPUT_SAMPLES_MIC_DELAY_MS != 0)
    configASSERT(AP_INPUT_SAMPLES_MIC_DELAY_BUF_SIZE_BYTES > 0);
    delay_buf_state.delay_buf = xStreamBufferCreate((size_t)AP_INPUT_SAMPLES_MIC_DELAY_BUF_SIZE_BYTES + AP_INPUT_SAMPLES_MIC_DELAY_CUR_FRAME_BYTES, 0);
    configASSERT(delay_buf_state.delay_buf);
#endif

    aec_init(&aec_state.aec_main_state,
             &aec_state.aec_shadow_state,
             &aec_state.aec_shared_state,
             &aec_state.aec_main_memory_pool[0],
             &aec_state.aec_shadow_memory_pool[0],
             AEC_MAX_Y_CHANNELS,
             AEC_MAX_X_CHANNELS,
             AEC_MAIN_FILTER_PHASES,
             AEC_SHADOW_FILTER_PHASES);
}

void audio_pipeline_init(
    void *input_app_data,
    void *output_app_data)
{
    const int stage_count = 2;
    const pipeline_stage_t stages[] = {
        (pipeline_stage_t)stage_delay,
        (pipeline_stage_t)stage_aec,
    };

    const configSTACK_DEPTH_TYPE stage_stack_sizes[] = {
        configMINIMAL_STACK_SIZE + RTOS_THREAD_STACK_SIZE(stage_delay) + RTOS_THREAD_STACK_SIZE(audio_pipeline_input_i),
        configMINIMAL_STACK_SIZE + RTOS_THREAD_STACK_SIZE(stage_aec) + RTOS_THREAD_STACK_SIZE(audio_pipeline_output_i),
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
#endif /* ON_TILE(1) */
