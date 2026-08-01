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

#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
audio_pipeline_debug_counters_t audio_pipeline_tile1_debug = {
    .magic = 0x54314442, /* T1DB */
};
static uint32_t fixed_delay_debug_frame_counter;
static uint16_t fixed_delay_aec_capture_preroll_remaining;
static fixed_delay_aec_capture_status_t fixed_delay_aec_capture_status = {
    .magic = AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_MAGIC,
    .total_bytes = AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_TOTAL_BYTES,
    .chunk_count = AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_CHUNKS,
    .state = AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_IDLE,
};
static int32_t DWORD_ALIGNED fixed_delay_aec_capture_samples
    [AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_FRAMES]
    [AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_CHANNELS]
    [AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_SAMPLES_PER_FRAME];
static int32_t fixed_delay_aec_capture_mic_prefix
    [AEC_MAX_Y_CHANNELS]
    [AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_PREFIX_SAMPLES];
static int32_t fixed_delay_aec_capture_ref_prefix
    [AEC_MAX_X_CHANNELS]
    [AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_PREFIX_SAMPLES];
static uint16_t fixed_delay_aec_capture_prefix_frame_index;
static uint16_t fixed_delay_aec_capture_prefix_sample_index;
static int fixed_delay_aec_capture_prefix_has_nonzero;
extern unsigned fixed_delay_aec_debug_get_recalc_bin(void);

void fixed_delay_aec_capture_arm(const fixed_delay_aec_capture_arm_t *arm)
{
    memset(fixed_delay_aec_capture_samples, 0, sizeof(fixed_delay_aec_capture_samples));
    memset(fixed_delay_aec_capture_mic_prefix, 0, sizeof(fixed_delay_aec_capture_mic_prefix));
    memset(fixed_delay_aec_capture_ref_prefix, 0, sizeof(fixed_delay_aec_capture_ref_prefix));
    fixed_delay_aec_capture_prefix_frame_index = 0;
    fixed_delay_aec_capture_prefix_sample_index = 0;
    fixed_delay_aec_capture_prefix_has_nonzero = 0;
    fixed_delay_aec_capture_status.magic = AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_MAGIC;
    fixed_delay_aec_capture_status.capture_id = arm->request_id;
    fixed_delay_aec_capture_status.base_frame_counter = 0;
    fixed_delay_aec_capture_status.total_bytes =
        AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_TOTAL_BYTES;
    fixed_delay_aec_capture_status.frames_captured = 0;
    fixed_delay_aec_capture_status.chunk_count =
        AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_CHUNKS;
    fixed_delay_aec_capture_status.selected_chunk = 0;
    fixed_delay_aec_capture_status.state =
        AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_ARMED;
    fixed_delay_aec_capture_status.reserved = 0;
    fixed_delay_aec_capture_preroll_remaining = 0;
}

void fixed_delay_aec_capture_get_status(fixed_delay_aec_capture_status_t *status)
{
    memcpy(status, &fixed_delay_aec_capture_status, sizeof(*status));
}

void fixed_delay_aec_capture_get_probe(fixed_delay_aec_capture_probe_t *probe)
{
    memset(probe, 0, sizeof(*probe));
    probe->magic = AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_MAGIC;
    probe->marker = 0x50524F42u; /* PROB */
    probe->base_frame_counter = fixed_delay_aec_capture_status.base_frame_counter;
    probe->total_bytes = fixed_delay_aec_capture_status.total_bytes;
    probe->selected_chunk = fixed_delay_aec_capture_status.selected_chunk;
    probe->chunk_count = fixed_delay_aec_capture_status.chunk_count;
    probe->frames_captured = fixed_delay_aec_capture_status.frames_captured;
    probe->prefix_sample_count = AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_PREFIX_SAMPLES;
    probe->prefix_frame_index = fixed_delay_aec_capture_prefix_frame_index;
    probe->prefix_sample_index = fixed_delay_aec_capture_prefix_sample_index;
    memcpy(probe->mic_input,
           fixed_delay_aec_capture_mic_prefix,
           sizeof(probe->mic_input));
    memcpy(probe->ref_input,
           fixed_delay_aec_capture_ref_prefix,
           sizeof(probe->ref_input));
}

int fixed_delay_aec_capture_select_chunk(uint16_t chunk_index)
{
    if (chunk_index >= AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_CHUNKS) {
        return -1;
    }
    fixed_delay_aec_capture_status.selected_chunk = chunk_index;
    return 0;
}

void fixed_delay_aec_capture_get_selected_chunk(
    fixed_delay_aec_capture_chunk_t *chunk)
{
    const uint16_t chunk_index = fixed_delay_aec_capture_status.selected_chunk;
    const size_t byte_offset =
        (size_t)chunk_index * AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_CHUNK_DATA_BYTES;

    memset(chunk, 0, sizeof(*chunk));
    chunk->magic = AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_MAGIC;
    chunk->capture_id = fixed_delay_aec_capture_status.capture_id;
    chunk->chunk_index = chunk_index;
    chunk->chunk_count = AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_CHUNKS;
    const size_t remaining =
        AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_TOTAL_BYTES - byte_offset;
    chunk->valid_bytes =
        (remaining < AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_CHUNK_DATA_BYTES) ?
        (uint8_t)remaining :
        AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_CHUNK_DATA_BYTES;
    if (chunk_index < AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_CHUNKS &&
        fixed_delay_aec_capture_status.state ==
            AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_DONE) {
        memcpy(chunk->data,
               ((const uint8_t *)fixed_delay_aec_capture_samples) + byte_offset,
               chunk->valid_bytes);
    }
}

static int fixed_delay_aec_capture_begin_frame(
    const int32_t mic_input[AEC_MAX_Y_CHANNELS][appconfAUDIO_PIPELINE_FRAME_ADVANCE],
    const int32_t ref_input[AEC_MAX_X_CHANNELS][appconfAUDIO_PIPELINE_FRAME_ADVANCE])
{
    int has_mic_nonzero = 0;
    int has_ref_nonzero = 0;
    int prefix_segment_found = 0;
    uint16_t prefix_sample_index = 0;

    if (fixed_delay_aec_capture_status.state ==
        AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_ARMED) {
        if (fixed_delay_aec_capture_preroll_remaining > 0) {
            fixed_delay_aec_capture_preroll_remaining--;
            return 0;
        }
        fixed_delay_aec_capture_status.state =
            AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_CAPTURING;
        fixed_delay_aec_capture_status.base_frame_counter = fixed_delay_debug_frame_counter;
        fixed_delay_aec_capture_status.frames_captured = 0;
    }

    if (fixed_delay_aec_capture_status.state !=
        AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_CAPTURING) {
        return 0;
    }

    if (fixed_delay_aec_capture_status.frames_captured >=
        AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_FRAMES) {
        return 0;
    }
    for (size_t ch = 0; ch < AEC_MAX_Y_CHANNELS; ch++) {
        for (size_t i = 0; i < appconfAUDIO_PIPELINE_FRAME_ADVANCE; i++) {
            if (mic_input[ch][i] != 0) {
                has_mic_nonzero = 1;
            }
        }
    }
    for (size_t ch = 0; ch < AEC_MAX_X_CHANNELS; ch++) {
        for (size_t i = 0; i < appconfAUDIO_PIPELINE_FRAME_ADVANCE; i++) {
            if (ref_input[ch][i] != 0) {
                has_ref_nonzero = 1;
            }
        }
    }
    if (has_mic_nonzero && has_ref_nonzero) {
        for (size_t i = 0;
             i <= appconfAUDIO_PIPELINE_FRAME_ADVANCE -
                    AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_PREFIX_SAMPLES;
             i++) {
            int segment_mic_nonzero = 0;
            int segment_ref_nonzero = 0;
            for (size_t ch = 0; ch < AEC_MAX_Y_CHANNELS; ch++) {
                for (size_t j = 0; j < AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_PREFIX_SAMPLES; j++) {
                    if (mic_input[ch][i + j] != 0) {
                        segment_mic_nonzero++;
                    }
                }
            }
            for (size_t ch = 0; ch < AEC_MAX_X_CHANNELS; ch++) {
                for (size_t j = 0; j < AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_PREFIX_SAMPLES; j++) {
                    if (ref_input[ch][i + j] != 0) {
                        segment_ref_nonzero++;
                    }
                }
            }
            if (segment_mic_nonzero >= 12 && segment_ref_nonzero >= 12) {
                prefix_sample_index = (uint16_t)i;
                prefix_segment_found = 1;
                break;
            }
        }
    }
    if (!fixed_delay_aec_capture_prefix_has_nonzero && prefix_segment_found) {
        for (size_t ch = 0; ch < AEC_MAX_Y_CHANNELS; ch++) {
            memcpy(fixed_delay_aec_capture_mic_prefix[ch],
                   &mic_input[ch][prefix_sample_index],
                   sizeof(fixed_delay_aec_capture_mic_prefix[ch]));
        }
        for (size_t ch = 0; ch < AEC_MAX_X_CHANNELS; ch++) {
            memcpy(fixed_delay_aec_capture_ref_prefix[ch],
                   &ref_input[ch][prefix_sample_index],
                   sizeof(fixed_delay_aec_capture_ref_prefix[ch]));
        }
        fixed_delay_aec_capture_prefix_frame_index =
            fixed_delay_aec_capture_status.frames_captured;
        fixed_delay_aec_capture_prefix_sample_index = prefix_sample_index;
        fixed_delay_aec_capture_prefix_has_nonzero = 1;
    }

    return 1;
}

static void fixed_delay_aec_capture_store_output(
    const int32_t stage1_output[AEC_MAX_Y_CHANNELS][appconfAUDIO_PIPELINE_FRAME_ADVANCE])
{
    if (fixed_delay_aec_capture_status.state !=
        AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_CAPTURING) {
        return;
    }

    uint16_t frame = fixed_delay_aec_capture_status.frames_captured;
    if (frame < AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_FRAMES) {
        for (size_t ch = 0; ch < AEC_MAX_Y_CHANNELS; ch++) {
            memcpy(fixed_delay_aec_capture_samples[frame][ch],
                   stage1_output[ch],
                   AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_SAMPLES_PER_FRAME *
                       sizeof(int32_t));
        }
        frame++;
        fixed_delay_aec_capture_status.frames_captured = frame;
    }

    if (frame >= AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_FRAMES) {
        fixed_delay_aec_capture_status.state =
            AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_DONE;
    }
}
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
#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    audio_pipeline_tile1_debug.input_enter++;
    audio_pipeline_tile1_debug.rx_len_before++; /* before pool acquire */
#endif
    xassert(rtos_osal_queue_receive(frame_free_queue,
                                    &frame_data,
                                    RTOS_OSAL_WAIT_FOREVER) == RTOS_OSAL_SUCCESS);
#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    audio_pipeline_tile1_debug.rx_len_after++; /* after pool acquire */
    audio_pipeline_tile1_debug.last_rx_len = (uint32_t) sizeof(frame_data_t);
#endif
    memset(frame_data, 0x00, sizeof(frame_data_t));

#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    audio_pipeline_tile1_debug.rx_data_after++; /* before audio_pipeline_input */
#endif
    audio_pipeline_input(input_app_data,
                       (int32_t *) frame_data->aec_reference_audio_samples,
                       appconfMIC_PIPELINE_REF_CHANNELS + appconfMIC_PIPELINE_INPUT_CHANNELS,
                       appconfAUDIO_PIPELINE_FRAME_ADVANCE);
#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    audio_pipeline_tile1_debug.input_return++;
#endif

    frame_data->vnr_pred_flag = 0;

    copy_mic_passthrough_to_processing(frame_data);
#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    audio_pipeline_tile1_debug.output_after++; /* input wrapper completed */
#endif

    return frame_data;
}

static int audio_pipeline_output_i(frame_data_t *frame_data,
                                   void *output_app_data)
{

#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    audio_pipeline_tile1_debug.output_enter++;
    audio_pipeline_tile1_debug.tx_before++;
#endif
    rtos_intertile_tx(intertile_ctx,
                      appconfAUDIOPIPELINE_PORT,
                      frame_data,
                      sizeof(frame_data_t));
#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
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

#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    int capture_current_frame = 0;
    frame_data->debug_frame_counter = ++fixed_delay_debug_frame_counter;
    frame_data->debug_aec_x_energy_recalc_bin = fixed_delay_aec_debug_get_recalc_bin();
    for (size_t ch = 0; ch < 2; ch++) {
        for (size_t i = 0; i < 4; i++) {
            frame_data->debug_mic_input[ch][i] = frame_data->samples[ch][i];
            frame_data->debug_ref_input[ch][i] = frame_data->aec_reference_audio_samples[ch][i];
        }
    }
    capture_current_frame = fixed_delay_aec_capture_begin_frame(
        frame_data->samples,
        frame_data->aec_reference_audio_samples);
#endif

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
#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    if (capture_current_frame) {
        fixed_delay_aec_capture_store_output(stage1_output);
    }
    for (size_t ch = 0; ch < 2; ch++) {
        for (size_t i = 0; i < 4; i++) {
            frame_data->debug_aec_output[ch][i] = stage1_output[ch][i];
        }
    }
#endif
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
