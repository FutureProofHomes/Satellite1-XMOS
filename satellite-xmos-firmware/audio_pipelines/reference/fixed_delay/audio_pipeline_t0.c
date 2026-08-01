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
#include "aec_api.h"
#include "agc_api.h"
#include "ic_api.h"
#include "ns_api.h"
#include "vnr_features_api.h"
#include "vnr_inference_api.h"

/* App headers */
#include "app_conf.h"
#include "audio_pipeline.h"
#include "audio_pipeline_dsp.h"
#include "audio_pipeline_control/audio_pipeline_control_settings.h"

#if appconfAUDIO_PIPELINE_FRAME_ADVANCE != 240
#error This pipeline is only configured for 240 frame advance
#endif

#define VNR_AGC_THRESHOLD (0.5)

#if ON_TILE(0)
static ic_stage_ctx_t DWORD_ALIGNED ic_stage_state = {};
static vnr_pred_stage_ctx_t DWORD_ALIGNED vnr_pred_stage_state = {};
static ns_stage_ctx_t DWORD_ALIGNED ns_stage_state = {};
static agc_stage_ctx_t DWORD_ALIGNED agc_stage_state = {};

#define AUDIO_PIPELINE_FRAME_POOL_DEPTH 3

static frame_data_t DWORD_ALIGNED frame_pool[AUDIO_PIPELINE_FRAME_POOL_DEPTH];
static rtos_osal_queue_t frame_free_queue_ctx;
static rtos_osal_queue_t *frame_free_queue;

#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
audio_pipeline_debug_counters_t audio_pipeline_tile0_debug = {
    .magic = 0x54304442, /* T0DB */
};
fixed_delay_stage_snapshot_t fixed_delay_stage_snapshot = {
    .magic = 0x46545353, /* FTSS */
};
static fixed_delay_ic_vnr_capture_status_t fixed_delay_ic_vnr_capture_status = {
    .magic = AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_MAGIC,
    .total_bytes = AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_TOTAL_BYTES,
    .chunk_count = AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_CHUNKS,
    .state = AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_IDLE,
};
static int32_t DWORD_ALIGNED fixed_delay_ic_vnr_capture_samples
    [AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_FRAMES]
    [AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_STREAMS]
    [AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_SAMPLES_PER_FRAME];
static fixed_delay_ic_vnr_capture_frame_meta_t fixed_delay_ic_vnr_capture_meta
    [AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_FRAMES];

void fixed_delay_ic_vnr_capture_arm(const fixed_delay_ic_vnr_capture_arm_t *arm)
{
    memset(fixed_delay_ic_vnr_capture_samples, 0, sizeof(fixed_delay_ic_vnr_capture_samples));
    memset(fixed_delay_ic_vnr_capture_meta, 0, sizeof(fixed_delay_ic_vnr_capture_meta));
    fixed_delay_ic_vnr_capture_status.magic = AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_MAGIC;
    fixed_delay_ic_vnr_capture_status.capture_id = arm->request_id;
    fixed_delay_ic_vnr_capture_status.base_frame_counter = 0;
    fixed_delay_ic_vnr_capture_status.total_bytes =
        AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_TOTAL_BYTES;
    fixed_delay_ic_vnr_capture_status.frames_captured = 0;
    fixed_delay_ic_vnr_capture_status.chunk_count =
        AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_CHUNKS;
    fixed_delay_ic_vnr_capture_status.selected_chunk = 0;
    fixed_delay_ic_vnr_capture_status.state =
        AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_ARMED;
    fixed_delay_ic_vnr_capture_status.reserved = 0;
}

void fixed_delay_ic_vnr_capture_get_status(fixed_delay_ic_vnr_capture_status_t *status)
{
    memcpy(status, &fixed_delay_ic_vnr_capture_status, sizeof(*status));
}

void fixed_delay_ic_vnr_capture_get_probe(fixed_delay_ic_vnr_capture_probe_t *probe)
{
    memset(probe, 0, sizeof(*probe));
    probe->magic = AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_MAGIC;
    probe->marker = 0x50524F42u; /* PROB */
    probe->base_frame_counter = fixed_delay_ic_vnr_capture_status.base_frame_counter;
    probe->total_bytes = fixed_delay_ic_vnr_capture_status.total_bytes;
    probe->selected_chunk = fixed_delay_ic_vnr_capture_status.selected_chunk;
    probe->chunk_count = fixed_delay_ic_vnr_capture_status.chunk_count;
    probe->frames_captured = fixed_delay_ic_vnr_capture_status.frames_captured;
    probe->stream_count = AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_STREAMS;
    probe->sample_bytes = AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_SAMPLE_BYTES;
    probe->meta_bytes = AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_META_BYTES;
}

int fixed_delay_ic_vnr_capture_select_chunk(uint16_t chunk_index)
{
    if (chunk_index >= AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_CHUNKS) {
        return -1;
    }
    fixed_delay_ic_vnr_capture_status.selected_chunk = chunk_index;
    return 0;
}

static uint8_t fixed_delay_ic_vnr_capture_byte_at(size_t byte_offset)
{
    if (byte_offset < AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_SAMPLE_BYTES) {
        return ((const uint8_t *)fixed_delay_ic_vnr_capture_samples)[byte_offset];
    }
    byte_offset -= AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_SAMPLE_BYTES;
    return ((const uint8_t *)fixed_delay_ic_vnr_capture_meta)[byte_offset];
}

void fixed_delay_ic_vnr_capture_get_selected_chunk(
    fixed_delay_ic_vnr_capture_chunk_t *chunk)
{
    const uint16_t chunk_index = fixed_delay_ic_vnr_capture_status.selected_chunk;
    const size_t byte_offset =
        (size_t)chunk_index * AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_CHUNK_DATA_BYTES;

    memset(chunk, 0, sizeof(*chunk));
    chunk->magic = AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_MAGIC;
    chunk->capture_id = fixed_delay_ic_vnr_capture_status.capture_id;
    chunk->chunk_index = chunk_index;
    chunk->chunk_count = AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_CHUNKS;
    const size_t remaining =
        AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_TOTAL_BYTES - byte_offset;
    chunk->valid_bytes =
        (remaining < AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_CHUNK_DATA_BYTES) ?
        (uint8_t)remaining :
        AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_CHUNK_DATA_BYTES;
    if (chunk_index < AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_CHUNKS &&
        fixed_delay_ic_vnr_capture_status.state ==
            AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_DONE) {
        for (size_t i = 0; i < chunk->valid_bytes; i++) {
            chunk->data[i] = fixed_delay_ic_vnr_capture_byte_at(byte_offset + i);
        }
    }
}

static int fixed_delay_ic_vnr_capture_begin_frame(
    uint32_t frame_counter,
    uint16_t *frame)
{
    if (fixed_delay_ic_vnr_capture_status.state ==
        AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_ARMED) {
        fixed_delay_ic_vnr_capture_status.state =
            AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_CAPTURING;
        fixed_delay_ic_vnr_capture_status.base_frame_counter = frame_counter;
        fixed_delay_ic_vnr_capture_status.frames_captured = 0;
    }

    if (fixed_delay_ic_vnr_capture_status.state !=
        AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_CAPTURING) {
        return 0;
    }

    if (fixed_delay_ic_vnr_capture_status.frames_captured >=
        AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_FRAMES) {
        return 0;
    }

    *frame = fixed_delay_ic_vnr_capture_status.frames_captured;
    return 1;
}

static void fixed_delay_ic_vnr_capture_store_inputs(
    uint16_t frame,
    const int32_t ic_input_y[appconfAUDIO_PIPELINE_FRAME_ADVANCE],
    const int32_t ic_input_x[appconfAUDIO_PIPELINE_FRAME_ADVANCE])
{
    memcpy(fixed_delay_ic_vnr_capture_samples[frame][0],
           ic_input_y,
           AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_SAMPLES_PER_FRAME * sizeof(int32_t));
    memcpy(fixed_delay_ic_vnr_capture_samples[frame][1],
           ic_input_x,
           AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_SAMPLES_PER_FRAME * sizeof(int32_t));
}

static void fixed_delay_ic_vnr_capture_store_frame(
    uint32_t frame_counter,
    uint16_t frame,
    const int32_t ic_output[appconfAUDIO_PIPELINE_FRAME_ADVANCE],
    const vnr_pred_state_t *vnr_pred_state,
    int32_t vnr_pred_flag,
    const ic_state_t *ic_state)
{
    if (fixed_delay_ic_vnr_capture_status.state !=
        AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_CAPTURING) {
        return;
    }

    if (frame < AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_FRAMES) {
        memcpy(fixed_delay_ic_vnr_capture_samples[frame][2],
               ic_output,
               AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_SAMPLES_PER_FRAME * sizeof(int32_t));
        fixed_delay_ic_vnr_capture_meta[frame].frame_counter = frame_counter;
        fixed_delay_ic_vnr_capture_meta[frame].input_vnr_pred_mant =
            vnr_pred_state->input_vnr_pred.mant;
        fixed_delay_ic_vnr_capture_meta[frame].input_vnr_pred_exp =
            vnr_pred_state->input_vnr_pred.exp;
        fixed_delay_ic_vnr_capture_meta[frame].output_vnr_pred_mant =
            vnr_pred_state->output_vnr_pred.mant;
        fixed_delay_ic_vnr_capture_meta[frame].output_vnr_pred_exp =
            vnr_pred_state->output_vnr_pred.exp;
        fixed_delay_ic_vnr_capture_meta[frame].vnr_pred_flag = vnr_pred_flag;
        fixed_delay_ic_vnr_capture_meta[frame].control_flag =
            ic_state->ic_adaption_controller_state.control_flag;
        fixed_delay_ic_vnr_capture_meta[frame].adapt_counter =
            ic_state->ic_adaption_controller_state.adapt_counter;
        frame++;
        fixed_delay_ic_vnr_capture_status.frames_captured = frame;
    }

    if (frame >= AUDIO_PIPELINE_FIXED_DELAY_IC_VNR_CAPTURE_FRAMES) {
        fixed_delay_ic_vnr_capture_status.state =
            AUDIO_PIPELINE_FIXED_DELAY_AEC_CAPTURE_DONE;
    }
}
#endif

#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
static void snapshot_frame_samples(int32_t *dst, const int32_t *src)
{
    for (size_t i = 0; i < AUDIO_PIPELINE_STAGE_SNAPSHOT_SAMPLES; i++) {
        dst[i] = src[i];
    }
}
#endif

static void *audio_pipeline_input_i(void *input_app_data)
{
    frame_data_t *frame_data;

    xassert(rtos_osal_queue_receive(frame_free_queue,
                                    &frame_data,
                                    RTOS_OSAL_WAIT_FOREVER) == RTOS_OSAL_SUCCESS);
    memset(frame_data, 0x00, sizeof(frame_data_t));

    size_t bytes_received = 0;
#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    audio_pipeline_tile0_debug.rx_len_before++;
#endif
    bytes_received = rtos_intertile_rx_len(
            intertile_ctx,
            appconfAUDIOPIPELINE_PORT,
            portMAX_DELAY);
#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    audio_pipeline_tile0_debug.rx_len_after++;
    audio_pipeline_tile0_debug.last_rx_len = bytes_received;
#endif

    xassert(bytes_received == sizeof(frame_data_t));

    rtos_intertile_rx_data(
            intertile_ctx,
            frame_data,
            bytes_received);
#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    audio_pipeline_tile0_debug.rx_data_after++;
#endif

    return frame_data;
}

static int audio_pipeline_output_i(frame_data_t *frame_data,
                                   void *output_app_data)
{

#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    audio_pipeline_tile0_debug.output_enter++;
    fixed_delay_stage_snapshot.aec_frame_counter = frame_data->debug_frame_counter;
    fixed_delay_stage_snapshot.ic_frame_counter = frame_data->debug_frame_counter;
    fixed_delay_stage_snapshot.ns_frame_counter = frame_data->debug_frame_counter;
    fixed_delay_stage_snapshot.agc_frame_counter = frame_data->debug_frame_counter;
    fixed_delay_stage_snapshot.sample_count = AUDIO_PIPELINE_STAGE_SNAPSHOT_SAMPLES;
    fixed_delay_stage_snapshot.aec_x_energy_recalc_bin =
        frame_data->debug_aec_x_energy_recalc_bin;
    fixed_delay_stage_snapshot.reserved = 0;
    memcpy(fixed_delay_stage_snapshot.mic_input,
           frame_data->debug_mic_input,
           sizeof(fixed_delay_stage_snapshot.mic_input));
    memcpy(fixed_delay_stage_snapshot.ref_input,
           frame_data->debug_ref_input,
           sizeof(fixed_delay_stage_snapshot.ref_input));
    memcpy(fixed_delay_stage_snapshot.aec_output,
           frame_data->debug_aec_output,
           sizeof(fixed_delay_stage_snapshot.aec_output));
    memcpy(fixed_delay_stage_snapshot.ic_output,
           frame_data->debug_ic_output,
           sizeof(fixed_delay_stage_snapshot.ic_output));
    memcpy(fixed_delay_stage_snapshot.ns_output,
           frame_data->debug_ns_output,
           sizeof(fixed_delay_stage_snapshot.ns_output));
    memcpy(fixed_delay_stage_snapshot.agc_output,
           frame_data->debug_agc_output,
           sizeof(fixed_delay_stage_snapshot.agc_output));
    fixed_delay_stage_snapshot.vnr_pred_flag = frame_data->vnr_pred_flag;
    fixed_delay_stage_snapshot.aec_ref_power_mant = frame_data->max_ref_energy.mant;
    fixed_delay_stage_snapshot.aec_ref_power_exp = frame_data->max_ref_energy.exp;
    fixed_delay_stage_snapshot.aec_corr_factor_mant = frame_data->aec_corr_factor.mant;
    fixed_delay_stage_snapshot.aec_corr_factor_exp = frame_data->aec_corr_factor.exp;
#endif
    int ret = audio_pipeline_output(output_app_data,
                                    (int32_t *) frame_data->samples,
                                    appconfMIC_PIPELINE_PROC_CHANNELS + appconfMIC_PIPELINE_REF_CHANNELS + appconfMIC_PIPELINE_INPUT_CHANNELS,
                                    appconfAUDIO_PIPELINE_FRAME_ADVANCE);
#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    audio_pipeline_tile0_debug.output_after++;
#endif
    xassert(ret == AUDIO_PIPELINE_FREE_FRAME);
    xassert(rtos_osal_queue_send(frame_free_queue,
                                 &frame_data,
                                 RTOS_OSAL_WAIT_FOREVER) == RTOS_OSAL_SUCCESS);
    return AUDIO_PIPELINE_DONT_FREE_FRAME;
}

static void stage_vnr_and_ic(frame_data_t *frame_data)
{
#if appconfAUDIO_PIPELINE_SKIP_IC_AND_VNR
#else
    int32_t DWORD_ALIGNED ic_output[appconfAUDIO_PIPELINE_FRAME_ADVANCE];
#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    uint16_t capture_frame = 0;
    int capture_current_frame = fixed_delay_ic_vnr_capture_begin_frame(
        frame_data->debug_frame_counter,
        &capture_frame);
    if (capture_current_frame) {
        fixed_delay_ic_vnr_capture_store_inputs(
            capture_frame,
            frame_data->samples[0],
            frame_data->samples[1]);
    }
#endif
    ic_filter(&ic_stage_state.state,
              frame_data->samples[0],
              frame_data->samples[1],
              ic_output);

    vnr_pred_state_t *vnr_pred_state = &vnr_pred_stage_state.vnr_pred_state;
    ic_calc_vnr_pred(&ic_stage_state.state, &vnr_pred_state->input_vnr_pred, &vnr_pred_state->output_vnr_pred);

    float_s32_t agc_vnr_threshold = f32_to_float_s32(VNR_AGC_THRESHOLD);
    frame_data->vnr_pred_flag = float_s32_gt(vnr_pred_stage_state.vnr_pred_state.output_vnr_pred, agc_vnr_threshold);

    ic_adapt(&ic_stage_state.state, vnr_pred_stage_state.vnr_pred_state.input_vnr_pred);

#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    if (capture_current_frame) {
        fixed_delay_ic_vnr_capture_store_frame(
            frame_data->debug_frame_counter,
            capture_frame,
            ic_output,
            vnr_pred_state,
            frame_data->vnr_pred_flag,
            &ic_stage_state.state);
    }
#endif

    /* Intentionally ignoring comms ch from here on out */
    memcpy(frame_data->samples[0], ic_output, appconfAUDIO_PIPELINE_FRAME_ADVANCE * sizeof(int32_t));
#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    snapshot_frame_samples(frame_data->debug_ic_output, ic_output);
#endif
#if appconfAUDIO_PIPELINE_STORE_IC_AUDIO    
    if (mic_output_pipeline_ref_overwrite_enabled()) {
        memcpy(frame_data->aec_reference_audio_samples[0], ic_output, appconfAUDIO_PIPELINE_FRAME_ADVANCE * sizeof(int32_t));   // Store the interference cancelled audio in the first reference channel
    }
#endif
#endif
}

static void stage_ns(frame_data_t *frame_data)
{
#if appconfAUDIO_PIPELINE_SKIP_NS
#else
    int32_t DWORD_ALIGNED ns_output[appconfAUDIO_PIPELINE_FRAME_ADVANCE];
    configASSERT(NS_FRAME_ADVANCE == appconfAUDIO_PIPELINE_FRAME_ADVANCE);
    ns_process_frame(
                &ns_stage_state.state,
                ns_output,
                frame_data->samples[0]);
    memcpy(frame_data->samples[0], ns_output, appconfAUDIO_PIPELINE_FRAME_ADVANCE * sizeof(int32_t));
#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    snapshot_frame_samples(frame_data->debug_ns_output, ns_output);
#endif
#if appconfAUDIO_PIPELINE_STORE_NS_AUDIO
    if (mic_output_pipeline_ref_overwrite_enabled()) {
        memcpy(frame_data->aec_reference_audio_samples[1], ns_output, appconfAUDIO_PIPELINE_FRAME_ADVANCE * sizeof(int32_t));   // Store NS audio in the second reference channel
    }
#endif
#endif
}

static void stage_agc(frame_data_t *frame_data)
{
#if appconfAUDIO_PIPELINE_SKIP_AGC
#else
    int32_t DWORD_ALIGNED agc_output[appconfAUDIO_PIPELINE_FRAME_ADVANCE];
    configASSERT(AGC_FRAME_ADVANCE == appconfAUDIO_PIPELINE_FRAME_ADVANCE);

    agc_stage_state.md.vnr_flag = frame_data->vnr_pred_flag;
    agc_stage_state.md.aec_ref_power = frame_data->max_ref_energy;
    agc_stage_state.md.aec_corr_factor = frame_data->aec_corr_factor;

    agc_process_frame(
            &agc_stage_state.state,
            agc_output,
            frame_data->samples[0],
            &agc_stage_state.md);
    memcpy(frame_data->samples, agc_output, appconfAUDIO_PIPELINE_FRAME_ADVANCE * sizeof(int32_t));
#if appconfDEVICE_CTRL_SPI && appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    snapshot_frame_samples(frame_data->debug_agc_output, agc_output);
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

    ic_init(&ic_stage_state.state);

    ns_init(&ns_stage_state.state);

    agc_init(&agc_stage_state.state, &AGC_PROFILE_ASR);
    agc_stage_state.md.aec_ref_power = AGC_META_DATA_NO_AEC;
    agc_stage_state.md.aec_corr_factor = AGC_META_DATA_NO_AEC;
}

void audio_pipeline_init(
    void *input_app_data,
    void *output_app_data)
{
    const int stage_count = 3;
    const pipeline_stage_t stages[] = {
        (pipeline_stage_t)stage_vnr_and_ic,
        (pipeline_stage_t)stage_ns,
        (pipeline_stage_t)stage_agc,
    };

    const configSTACK_DEPTH_TYPE stage_stack_sizes[] = {
        configMINIMAL_STACK_SIZE + RTOS_THREAD_STACK_SIZE(stage_vnr_and_ic) + RTOS_THREAD_STACK_SIZE(audio_pipeline_input_i),
        configMINIMAL_STACK_SIZE + RTOS_THREAD_STACK_SIZE(stage_ns),
        configMINIMAL_STACK_SIZE + RTOS_THREAD_STACK_SIZE(stage_agc) + RTOS_THREAD_STACK_SIZE(audio_pipeline_output_i),
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

#endif /* ON_TILE(0)*/
