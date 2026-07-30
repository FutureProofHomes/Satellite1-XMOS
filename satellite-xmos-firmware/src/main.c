// Copyright 2020-2024 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

#include <platform.h>
#include <xs1.h>
#include <xcore/channel.h>
#include <stdbool.h>
#include <string.h>

/* FreeRTOS headers */
#include "FreeRTOS.h"
#include "task.h"
#include "stream_buffer.h"
#include "queue.h"

/* Library headers */
#include "rtos_printf.h"
#include "src.h"

/* App headers */
#include "app_conf.h"
#include "platform/platform_init.h"
#include "platform/driver_instances.h"
#include "platform/platform_conf.h"
#if appconfUSB_ENABLED
#include "usb_support.h"
#include "usb_audio.h"
#include "usb_cdc.h"
#endif
#include "audio_pipeline.h"
#include "speaker_pipeline.h"
#include "audio_runtime/audio_runtime_gain.h"
#include "audio_pipeline_control/audio_pipeline_control_servicer.h"
#include "dfu_servicer.h"
#include "gpio/gpio_servicer.h"
#include "led_ring/led_ring_servicer.h"


/* Config headers for sw_pll */
#include "sw_pll.h"

volatile int mic_from_usb = appconfMIC_SRC_DEFAULT;
volatile int aec_ref_source = appconfAEC_REF_DEFAULT;

#define DEVICE_STATUS_READY_REGISTER_IDX   0
#define DEVICE_STATUS_READY_VALUE          1

#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
rtos_osal_queue_t *ref_input_queue;
rtos_osal_queue_t *mic_input_sim_queue;
static rtos_osal_queue_t ref_input_queue_ctx;
static rtos_osal_queue_t mic_input_sim_queue_ctx;
static rtos_osal_queue_t ref_input_free_queue_ctx;
static rtos_osal_queue_t mic_input_sim_free_queue_ctx;
static rtos_osal_queue_t *ref_input_free_queue;
static rtos_osal_queue_t *mic_input_sim_free_queue;

#define AUDIO_FRAME_POOL_DEPTH 3

static int32_t ref_input_frame_pool[AUDIO_FRAME_POOL_DEPTH]
                                  [appconfAUDIO_PIPELINE_FRAME_ADVANCE]
                                  [appconfMIC_PIPELINE_REF_CHANNELS];
static int32_t mic_input_sim_frame_pool[AUDIO_FRAME_POOL_DEPTH]
                                      [appconfAUDIO_PIPELINE_FRAME_ADVANCE]
                                      [appconfMIC_PIPELINE_INPUT_CHANNELS];

#if appconfDEVICE_CTRL_SPI
static servicer_t speaker_audio_pipeline_servicer_state;
static speaker_pipeline_settings_runtime_t speaker_pipeline_settings_runtime;
static mic_input_pipeline_settings_runtime_t mic_input_pipeline_settings_runtime;
static audio_pipeline_servicer_ctx_t speaker_audio_pipeline_servicer_context;
static servicer_register_ctx_t speaker_audio_pipeline_servicer_reg_ctx;
#endif

#define AUDIO_PIPELINE_QUEUE_WAIT_TICKS pdMS_TO_TICKS(50)

static int frame_pool_try_acquire(rtos_osal_queue_t *free_queue,
                                  void **frame_data)
{
    xassert(free_queue != NULL);
    xassert(frame_data != NULL);

    return rtos_osal_queue_receive(free_queue, frame_data, RTOS_OSAL_NO_WAIT);
}

static void frame_pool_release(rtos_osal_queue_t *free_queue,
                               void *frame_data)
{
    if (frame_data == NULL) {
        return;
    }

    xassert(rtos_osal_queue_send(free_queue,
                                 &frame_data,
                                 RTOS_OSAL_NO_WAIT) == RTOS_OSAL_SUCCESS);
}
#endif

#if ON_TILE(0)
#if appconfDEVICE_CTRL_SPI
static servicer_t mic_audio_pipeline_servicer_state;
mic_output_pipeline_settings_runtime_t mic_output_pipeline_settings_runtime;
static audio_pipeline_servicer_ctx_t mic_audio_pipeline_servicer_context;
static servicer_register_ctx_t mic_audio_pipeline_servicer_reg_ctx;
#endif
#endif

#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
static int32_t get_packaged_lane_sample(const int32_t *samples,
                                        size_t frame_count,
                                        uint8_t lane_index,
                                        size_t frame_index_16k)
{
    size_t channel = lane_index / 3;
    size_t phase = lane_index % 3;
    size_t frame_index_48k = (frame_index_16k * 3) + phase;

    xassert(channel < appconfAUDIO_SPK_CHANNELS);
    xassert(frame_index_48k < frame_count);

    return *(samples + (channel * frame_count) + frame_index_48k);
}

static uint8_t remap_packaged_payload_lane(uint8_t payload_lane,
                                           uint8_t sync_phase)
{
    xassert(payload_lane >= AUDIO_PIPELINE_PACKAGED_PAYLOAD_INDEX_MIN);
    xassert(payload_lane <= AUDIO_PIPELINE_PACKAGED_PAYLOAD_INDEX_MAX);
    xassert(sync_phase < 3);

    uint8_t channel = payload_lane / 3;
    uint8_t phase = payload_lane % 3;
    uint8_t mapped_phase = (phase + sync_phase) % 3;
    return (channel * 3) + mapped_phase;
}

static uint8_t detect_packaged_sync_phase(const int32_t *samples,
                                          size_t frame_count,
                                          int *best_score_out)
{
    uint8_t best_phase = 0;
    int best_score = -1;

    for (uint8_t phase = 0; phase < 3; phase++) {
        int score = 0;
        for (size_t frame = 0; frame < AUDIO_PIPELINE_PACKAGED_SNAPSHOT_SAMPLES; frame++) {
            int32_t sample = get_packaged_lane_sample(samples, frame_count, phase, frame);
            if (sample == AUDIO_PIPELINE_PACKAGED_SYNC_WORD) {
                score++;
            }
        }
        if (score > best_score) {
            best_score = score;
            best_phase = phase;
        }
    }

    if (best_score_out != NULL) {
        *best_score_out = best_score;
    }

    return best_phase;
}
#endif

#if ON_TILE(0)
static int32_t get_mic_output_sample(const int32_t *samples,
                                     size_t frame_count,
                                     uint8_t channel_index,
                                     size_t frame_index)
{
    if (channel_index == AUDIO_PIPELINE_OUTPUT_VIRTUAL_SYNC_CHANNEL) {
        return AUDIO_PIPELINE_PACKAGED_SYNC_WORD;
    }

    xassert(channel_index < appconfMIC_PIPELINE_PROC_CHANNELS +
                            appconfMIC_PIPELINE_REF_CHANNELS +
                            appconfMIC_PIPELINE_INPUT_CHANNELS);
    return *(samples + frame_index + (channel_index * frame_count));
}
#endif

void speaker_pipeline_input(void *input_app_data,
                        int32_t *input_audio_frames,
                        size_t ch_count,
                        size_t frame_count)
{
#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
    if (!appconfUSB_AUDIO_ENABLED || aec_ref_source == appconfAEC_REF_I2S) {
        /* This shouldn't need to block given it shares a clock with the PDM mics */

        xassert(frame_count == appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE);
        /* I2S provides sample channel format */
        int32_t tmp[appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE][appconfI2S_AUDIO_INPUTS][appconfAUDIO_SPK_CHANNELS];
        int32_t *tmpptr = (int32_t *)input_audio_frames;

        size_t rx_count =
        rtos_i2s_rx(i2s_ctx,
                    (int32_t*) tmp,
                    frame_count,
                    portMAX_DELAY);
        xassert(rx_count == frame_count);

        for (int i=0; i<frame_count; i++) {
            /* ref is first */
            *(tmpptr + i) = tmp[i][0][0];
            *(tmpptr + i + frame_count) = tmp[i][0][1];
        }
    }

#if appconfUSB_AUDIO_ENABLED
    int32_t **usb_mic_audio_frame = NULL;
    if (true) {
        usb_mic_audio_frame = (int32_t **) input_audio_frames;
        /*
        * As noted above, this does not block.
        * and expects ref L, ref R, mic 0, mic 1
        */
        usb_audio_recv(intertile_usb_audio_ctx,
            frame_count,
            usb_mic_audio_frame,
            ch_count);
    }
#endif    
#endif
}

int speaker_pipeline_output(void *output_app_data,
                        int32_t *output_audio_frames,
                        size_t ch_count,
                        size_t frame_count)
{
#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)    
    (void) output_app_data;
    bool packaged_ref_mode = false;
    bool packaged_mic_mode = false;
    bool packaged_sync_missing = false;
    uint8_t packaged_sync_phase = 0;
    mic_input_pipeline_settings_t default_mic_input_settings;
    mic_input_pipeline_settings_t *mic_input_settings = NULL;

    xassert(frame_count == appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE);

#if appconfDEVICE_CTRL_SPI
    mic_input_settings = &mic_input_pipeline_settings_runtime.active;
#endif
    if (mic_input_settings == NULL) {
        mic_input_pipeline_settings_default(&default_mic_input_settings);
        mic_input_settings = &default_mic_input_settings;
    }

    if (appconfI2S_AUDIO_SAMPLE_RATE == 3 * appconfAUDIO_PIPELINE_SAMPLE_RATE) {
        int packaged_sync_score = 0;

        packaged_ref_mode =
            mic_input_settings->ref_source_mode == AUDIO_PIPELINE_REF_SOURCE_PACKAGED_INPUT;
        packaged_mic_mode =
            mic_input_settings->mic_source_mode == AUDIO_PIPELINE_MIC_SOURCE_PACKAGED_INPUT;
        if (packaged_ref_mode || packaged_mic_mode) {
            packaged_sync_phase = detect_packaged_sync_phase(output_audio_frames,
                                                            frame_count,
                                                            &packaged_sync_score);
            if (packaged_sync_score == 0) {
                packaged_sync_missing = true;
                packaged_ref_mode = false;
                packaged_mic_mode = false;
            }
        }
    }
    
    /* I2S expects sample channel format */
    int32_t tmp[appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE][1][appconfAUDIO_SPK_CHANNELS];
    int32_t *tmpptr = (int32_t *)output_audio_frames;

#if appconfSPEAKER_OUTPUT_TEST_PATTERN
    const int32_t lane_pattern[AUDIO_PIPELINE_PACKAGED_INPUT_CHANNEL_COUNT] = {
        0x11111111,
        0x22222222,
        0x33333333,
        0x44444444,
        0x55555555,
        0x66666666,
    };
    xassert(appconfI2S_AUDIO_SAMPLE_RATE == 3 * appconfAUDIO_PIPELINE_SAMPLE_RATE);
    for (size_t frame = 0; frame < appconfAUDIO_PIPELINE_FRAME_ADVANCE; frame++) {
        size_t out = frame * 3;
        *(tmpptr + (0 * frame_count) + out + 0) = lane_pattern[0];
        *(tmpptr + (0 * frame_count) + out + 1) = lane_pattern[1];
        *(tmpptr + (0 * frame_count) + out + 2) = lane_pattern[2];
        *(tmpptr + (1 * frame_count) + out + 0) = lane_pattern[3];
        *(tmpptr + (1 * frame_count) + out + 1) = lane_pattern[4];
        *(tmpptr + (1 * frame_count) + out + 2) = lane_pattern[5];
    }
#endif

    for (int j=0; j<frame_count; j++) {
        tmp[j][0][0] = *(tmpptr+j+(0*frame_count));    // ref 0 -> DAC
        tmp[j][0][1] = *(tmpptr+j+(1*frame_count));    // ref 1 -> DAC
    }

    if (packaged_ref_mode) {
        for (size_t frame = 0; frame < appconfAUDIO_PIPELINE_FRAME_ADVANCE; frame++) {
            tmp[frame * 3][0][0] =
                get_packaged_lane_sample(tmpptr,
                                         frame_count,
                                         remap_packaged_payload_lane(
                                             mic_input_settings->ref_input_channel_map[0],
                                             packaged_sync_phase),
                                         frame);
            tmp[frame * 3][0][1] =
                get_packaged_lane_sample(tmpptr,
                                         frame_count,
                                         remap_packaged_payload_lane(
                                             mic_input_settings->ref_input_channel_map[1],
                                             packaged_sync_phase),
                                         frame);
            tmp[(frame * 3) + 1][0][0] = tmp[frame * 3][0][0];
            tmp[(frame * 3) + 1][0][1] = tmp[frame * 3][0][1];
            tmp[(frame * 3) + 2][0][0] = tmp[frame * 3][0][0];
            tmp[(frame * 3) + 2][0][1] = tmp[frame * 3][0][1];
        }
    }
    
    // send to DAC
    rtos_i2s_tx_1(i2s_ctx,
                (int32_t*) tmp,
                frame_count,
                portMAX_DELAY);
    
    void *frame_data = NULL;
    xassert(rtos_osal_queue_receive(ref_input_free_queue,
                                    &frame_data,
                                    RTOS_OSAL_WAIT_FOREVER) == RTOS_OSAL_SUCCESS);
    
    // down sample reference signal to 16kHz if needed
    if (packaged_ref_mode) {
        int32_t *refptr = (int32_t *) frame_data;
        for (size_t frame = 0; frame < appconfAUDIO_PIPELINE_FRAME_ADVANCE; frame++) {
            *(refptr++) = tmp[frame * 3][0][0];
            *(refptr++) = tmp[frame * 3][0][1];
        }
    } else if (appconfI2S_AUDIO_SAMPLE_RATE == 3*appconfAUDIO_PIPELINE_SAMPLE_RATE) {
        static int64_t sum[2];
        static int32_t src_data[2][SRC_FF3V_FIR_NUM_PHASES][SRC_FF3V_FIR_TAPS_PER_PHASE] __attribute__((aligned (8)));
        int32_t tmp_out[appconfAUDIO_PIPELINE_FRAME_ADVANCE][1][appconfMIC_PIPELINE_REF_CHANNELS];
        
        for( int frame=0; frame < frame_count; frame +=3 ){
            sum[0] = src_ds3_voice_add_sample(0, src_data[0][0], src_ff3v_fir_coefs[0], tmp[frame][0][0]);
            sum[1] = src_ds3_voice_add_sample(0, src_data[1][0], src_ff3v_fir_coefs[0], tmp[frame][0][1]);

            sum[0] = src_ds3_voice_add_sample(sum[0], src_data[0][1], src_ff3v_fir_coefs[1], tmp[frame+1][0][0]);
            sum[1] = src_ds3_voice_add_sample(sum[1], src_data[1][1], src_ff3v_fir_coefs[1], tmp[frame+1][0][1]);

            tmp_out[frame/3][0][0] = src_ds3_voice_add_final_sample(sum[0], src_data[0][2], src_ff3v_fir_coefs[2], tmp[frame+2][0][0]);
            tmp_out[frame/3][0][1] = src_ds3_voice_add_final_sample(sum[1], src_data[1][2], src_ff3v_fir_coefs[2], tmp[frame+2][0][1]);
        }
        memcpy( frame_data, tmp_out, appconfAUDIO_PIPELINE_FRAME_ADVANCE * appconfMIC_PIPELINE_REF_CHANNELS * sizeof( int32_t ) );
    } else {
      memcpy( frame_data, tmp, appconfAUDIO_PIPELINE_FRAME_ADVANCE * appconfMIC_PIPELINE_REF_CHANNELS * sizeof( int32_t ) );
    }
    
    // send to microphone pipeline as reference
    (void) rtos_osal_queue_send(ref_input_queue,
                                &frame_data,
                                RTOS_OSAL_WAIT_FOREVER);

    if (packaged_sync_missing) {
        void *stale_mic_frame_data;

        while (rtos_osal_queue_receive(mic_input_sim_queue,
                                       &stale_mic_frame_data,
                                       RTOS_OSAL_NO_WAIT) == RTOS_OSAL_SUCCESS) {
            frame_pool_release(mic_input_sim_free_queue, stale_mic_frame_data);
        }
    }

    if (packaged_mic_mode) {
        void *mic_frame_data = NULL;
        if (frame_pool_try_acquire(mic_input_sim_free_queue,
                                   &mic_frame_data) != RTOS_OSAL_SUCCESS) {
            goto skip_mic_enqueue;
        }

        int32_t *mic_dst = (int32_t *) mic_frame_data;
        xassert(appconfMIC_PIPELINE_INPUT_CHANNELS ==
                AUDIO_PIPELINE_MIC_INPUT_CHANNEL_MAP_COUNT);
        for (size_t mic_ch = 0; mic_ch < appconfMIC_PIPELINE_INPUT_CHANNELS; mic_ch++) {
            for (size_t frame = 0; frame < appconfAUDIO_PIPELINE_FRAME_ADVANCE; frame++) {
                int32_t sample =
                    get_packaged_lane_sample(tmpptr,
                                             frame_count,
                                             remap_packaged_payload_lane(
                                                 mic_input_settings->mic_input_channel_map[mic_ch],
                                                 packaged_sync_phase),
                                             frame);
                *(mic_dst + (mic_ch * appconfAUDIO_PIPELINE_FRAME_ADVANCE) + frame) = sample;
            }
        }

        if (rtos_osal_queue_send(mic_input_sim_queue,
                                 &mic_frame_data,
                                 AUDIO_PIPELINE_QUEUE_WAIT_TICKS) != RTOS_OSAL_SUCCESS) {
            frame_pool_release(mic_input_sim_free_queue, mic_frame_data);
        }

skip_mic_enqueue:
        ;
    }

#endif
    return AUDIO_PIPELINE_FREE_FRAME;
}



void audio_pipeline_input(void *input_app_data,
                        int32_t *input_audio_frames,
                        size_t ch_count,
                        size_t frame_count)
{
    (void) input_app_data;
    int32_t *mic_data = input_audio_frames + (appconfMIC_PIPELINE_REF_CHANNELS * frame_count);
    int32_t **mic_ptr = (int32_t **) mic_data;
#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
    bool packaged_mic_mode = false;
    mic_input_pipeline_settings_t default_mic_input_settings;
    mic_input_pipeline_settings_t *mic_input_settings = NULL;
#endif

    static int flushed;
    while (!flushed) {
        size_t received;
        received = rtos_mic_array_rx(mic_array_ctx,
                                     mic_ptr,
                                     frame_count,
                                     0);
        if (received == 0) {
            rtos_mic_array_rx(mic_array_ctx,
                              mic_ptr,
                              frame_count,
                              portMAX_DELAY);
            flushed = 1;
        }
    }

#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
    if (appconfI2S_AUDIO_SAMPLE_RATE == 3 * appconfAUDIO_PIPELINE_SAMPLE_RATE) {
#if appconfDEVICE_CTRL_SPI
        mic_input_settings = &mic_input_pipeline_settings_runtime.active;
#endif
        if (mic_input_settings == NULL) {
            mic_input_pipeline_settings_default(&default_mic_input_settings);
            mic_input_settings = &default_mic_input_settings;
        }

        packaged_mic_mode =
            mic_input_settings->mic_source_mode == AUDIO_PIPELINE_MIC_SOURCE_PACKAGED_INPUT;
    }

    //read the speaker pipeline output as reference
    void *frame_data;
    if (rtos_osal_queue_receive(ref_input_queue,
                                &frame_data,
                                RTOS_OSAL_WAIT_FOREVER) == RTOS_OSAL_SUCCESS) {
        int32_t *tmpptr = (int32_t *)input_audio_frames;
        int32_t *refptr = (int32_t *)frame_data;

        for (int i=0; i<frame_count; i++) {
            /* ref is first */
            *(tmpptr + i) = *(refptr++);
            *(tmpptr + i + frame_count) = *(refptr++);
        }

        frame_pool_release(ref_input_free_queue, frame_data);
    }
#endif


    /*
     * NOTE: ALWAYS receive the next frame from the PDM mics,
     * even if USB is the current mic source. The controls the
     * timing since usb_audio_recv() does not block and will
     * receive all zeros if no frame is available yet.
     */
    rtos_mic_array_rx(mic_array_ctx,
                      mic_ptr,
                      frame_count,
                      portMAX_DELAY);

#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
    if (packaged_mic_mode) {
        void *sim_mic_frame_data;

        if (rtos_osal_queue_receive(mic_input_sim_queue,
                                    &sim_mic_frame_data,
                                    AUDIO_PIPELINE_QUEUE_WAIT_TICKS) == RTOS_OSAL_SUCCESS) {
            memcpy(mic_data,
                   sim_mic_frame_data,
                   appconfAUDIO_PIPELINE_FRAME_ADVANCE *
                       appconfMIC_PIPELINE_INPUT_CHANNELS * sizeof(int32_t));
            frame_pool_release(mic_input_sim_free_queue, sim_mic_frame_data);
        }
    }

#if appconfMIC_PASSTHROUGH_TEST_PATTERN
    xassert(appconfMIC_PIPELINE_INPUT_CHANNELS >= 4);
    for (size_t frame = 0; frame < frame_count; frame++) {
        *(mic_data + (0 * frame_count) + frame) = 0x11111111;
        *(mic_data + (1 * frame_count) + frame) = 0x22222222;
        *(mic_data + (2 * frame_count) + frame) = 0x33333333;
        *(mic_data + (3 * frame_count) + frame) = 0x44444444;
    }
#endif

#if appconfDEVICE_CTRL_SPI
    if (mic_input_settings == NULL) {
        mic_input_settings = &mic_input_pipeline_settings_runtime.active;
    }

    audio_runtime_apply_input_gains_q24(input_audio_frames,
                                        frame_count,
                                        appconfMIC_PIPELINE_REF_CHANNELS,
                                        appconfMIC_PIPELINE_INPUT_CHANNELS,
                                        mic_input_settings->ref_gain,
                                        mic_input_settings->mic_gain);
#endif
#endif

}

bool mic_output_pipeline_ref_overwrite_enabled(void)
{
#if appconfDEVICE_CTRL_SPI && ON_TILE(0)
    return mic_output_pipeline_settings_runtime.active
        .overwrite_ref_with_ic_ns_output;
#else
    return true;
#endif
}

int audio_pipeline_output(void *output_app_data,
                        int32_t *output_audio_frames,
                        size_t ch_count,
                        size_t frame_count)
{
    (void) output_app_data;

#if ON_TILE(0)

#if appconfI2S_ENABLED
    mic_output_pipeline_settings_t *mic_settings = NULL;
    mic_output_pipeline_settings_t default_mic_settings;
    uint8_t i2s_channel_map[AUDIO_PIPELINE_OUTPUT_CHANNEL_COUNT];
    uint8_t upsample_channel_map[AUDIO_PIPELINE_UPSAMPLE_CHANNEL_MAP_COUNT];
    uint8_t pack_extra_upsample_channels = 0;

#ifndef appconfMIC_OUTPUT_TEST_PATTERN
#define appconfMIC_OUTPUT_TEST_PATTERN 0
#endif

    xassert(frame_count == appconfAUDIO_PIPELINE_FRAME_ADVANCE);
    /* I2S expects sample channel format */
    int32_t tmp[appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE][1][appconfMIC_PIPELINE_OUT_CHANNELS];
    int32_t *tmpptr = (int32_t *)output_audio_frames;

#if appconfDEVICE_CTRL_SPI
    mic_settings = &mic_output_pipeline_settings_runtime.active;
#endif

    if (mic_settings == NULL) {
        mic_output_pipeline_settings_default(&default_mic_settings);
        mic_settings = &default_mic_settings;
    }

    memcpy(i2s_channel_map,
           mic_settings->i2s_channel_map,
           sizeof(i2s_channel_map));
    memcpy(upsample_channel_map,
           mic_settings->upsample_channel_map,
           sizeof(upsample_channel_map));
    pack_extra_upsample_channels = mic_settings->pack_extra_upsample_channels;
     
     // 0 : proc 0, AEC+IC+NS+AGC audio
     // 1 : proc 1, mic 1 audio with AEC applied
     // 2 : ref 0, overwritten by AEC+IC output
     // 3 : ref 1, overwritten by AEC+IC+NS output
     // 4 : mic 0
     // 5 : mic 1

      if (appconfI2S_AUDIO_SAMPLE_RATE == 3*appconfAUDIO_PIPELINE_SAMPLE_RATE) {
        // duplicate to 48kHz
        for( int in_frame=0, out_frame=0; in_frame < frame_count; in_frame++, out_frame += 3 ){
            if (pack_extra_upsample_channels) {
                tmp[out_frame][0][0] =
                    get_mic_output_sample(tmpptr,
                                          frame_count,
                                          upsample_channel_map[0],
                                          in_frame);
                tmp[out_frame][0][1] =
                    get_mic_output_sample(tmpptr,
                                          frame_count,
                                          upsample_channel_map[1],
                                          in_frame);
                tmp[out_frame+1][0][0] =
                    get_mic_output_sample(tmpptr,
                                          frame_count,
                                          upsample_channel_map[2],
                                          in_frame);
                tmp[out_frame+1][0][1] =
                    get_mic_output_sample(tmpptr,
                                          frame_count,
                                          upsample_channel_map[3],
                                          in_frame);
                tmp[out_frame+2][0][0] =
                    get_mic_output_sample(tmpptr,
                                          frame_count,
                                          upsample_channel_map[4],
                                          in_frame);
                tmp[out_frame+2][0][1] =
                    get_mic_output_sample(tmpptr,
                                          frame_count,
                                          upsample_channel_map[5],
                                          in_frame);
            } else {
                int32_t smpl_ch0 = get_mic_output_sample(tmpptr,
                                                         frame_count,
                                                         i2s_channel_map[0],
                                                         in_frame);
                int32_t smpl_ch1 = get_mic_output_sample(tmpptr,
                                                         frame_count,
                                                         i2s_channel_map[1],
                                                         in_frame);

                tmp[out_frame][0][0] = smpl_ch0;
                tmp[out_frame][0][1] = smpl_ch1;
                tmp[out_frame+1][0][0] = smpl_ch0;
                tmp[out_frame+1][0][1] = smpl_ch1;
                tmp[out_frame+2][0][0] = smpl_ch0;
                tmp[out_frame+2][0][1] = smpl_ch1;
            }
        }
    } else {
        for (int j=0; j<frame_count; j++) {
            tmp[j][0][0] = get_mic_output_sample(tmpptr,
                                                 frame_count,
                                                 i2s_channel_map[0],
                                                 j);
            tmp[j][0][1] = get_mic_output_sample(tmpptr,
                                                 frame_count,
                                                 i2s_channel_map[1],
                                                 j);
        }
    }

#if appconfMIC_OUTPUT_TEST_PATTERN
    for (int j = 0; j < appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE; j++) {
        uint32_t low = ((uint32_t)j) & 0x00FFFFFFU;
        tmp[j][0][0] = (int32_t)((1U << 24) | low);
        tmp[j][0][1] = (int32_t)((2U << 24) | low);
    }
#endif
    
    
    rtos_i2s_tx(i2s_ctx,
                (int32_t*) tmp,
                appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE,
                portMAX_DELAY);
#endif

#if appconfUSB_AUDIO_ENABLED
    usb_audio_send(intertile_usb_audio_ctx,
                frame_count,
                (int32_t **) output_audio_frames,
                6);
#endif
#endif

    return AUDIO_PIPELINE_FREE_FRAME;
}




void vApplicationMallocFailedHook(void)
{
    rtos_printf("Malloc Failed on tile %d!\n", THIS_XCORE_TILE);
    xassert(0);
    for(;;);
}

static void init_watchdog(void)
{
    //xin : 24 Mhz, decrement WATCHDOG_COUNT every 2.7 ms:
    write_sswitch_reg_no_ack(get_local_tile_id(), XS1_SSWITCH_WATCHDOG_PRESCALER_WRAP_NUM, (0xFFFF));
    //trigger watchdog after ~11s of inactivity    
    write_sswitch_reg_no_ack(get_local_tile_id(), XS1_SSWITCH_WATCHDOG_COUNT_NUM, 0xFFF );
    write_sswitch_reg_no_ack(get_local_tile_id(), XS1_SSWITCH_WATCHDOG_CFG_NUM, (1 << XS1_WATCHDOG_COUNT_ENABLE_SHIFT) | (1 << XS1_WATCHDOG_TRIGGER_ENABLE_SHIFT) );
}

static void reset_watchdog(void)
{
    //reset watchdog to max
    write_sswitch_reg_no_ack(get_local_tile_id(), XS1_SSWITCH_WATCHDOG_COUNT_NUM, 0xFFF );
}
static void mem_analysis(void)
{
	for (;;) {
		rtos_printf("Tile[%d]:\n\tMinimum heap free: %d\n\tCurrent heap free: %d\n", THIS_XCORE_TILE, xPortGetMinimumEverFreeHeapSize(), xPortGetFreeHeapSize());
#if ON_TILE(0)        
        reset_watchdog();
#endif        
        vTaskDelay(pdMS_TO_TICKS(5000));
	}
}

#if ON_TILE(0) && appconfDEVICE_CTRL_SPI
static void device_control_ready_task(void *arg)
{
    device_control_t *device_control_ctx = arg;

    xassert(device_control_ctx != NULL);

    while (device_control_ctx->status_buffer == NULL) {
        vTaskDelay(pdMS_TO_TICKS(10));
    }

    device_control_set_resource_status(device_control_ctx,
                                       DEVICE_STATUS_READY_REGISTER_IDX,
                                       DEVICE_STATUS_READY_VALUE);

    vTaskDelete(NULL);
}
#endif

void startup_task(void *arg)
{
    rtos_printf("Startup task running from tile %d on core %d\n", THIS_XCORE_TILE, portGET_CORE_ID());
    platform_start();


#if appconfDEVICE_CTRL_SPI
    device_control_t *device_control_ctx[1] = {device_control_spi_ctx}; 

#if ON_TILE(0)
    gpio_servicer_start(device_control_gpio_ctx, device_control_ctx, 1 );

    mic_output_pipeline_settings_runtime_init(&mic_output_pipeline_settings_runtime);
    audio_pipeline_tile0_servicer_init(&mic_audio_pipeline_servicer_state);

    mic_audio_pipeline_servicer_context.servicer = &mic_audio_pipeline_servicer_state;
    mic_audio_pipeline_servicer_context.mic_output_settings =
        &mic_output_pipeline_settings_runtime;
    mic_audio_pipeline_servicer_context.speaker_settings = NULL;
    mic_audio_pipeline_servicer_context.mic_input_settings = NULL;
    mic_audio_pipeline_servicer_context.doa = NULL;

    mic_audio_pipeline_servicer_reg_ctx.servicer = &mic_audio_pipeline_servicer_state;
    mic_audio_pipeline_servicer_reg_ctx.device_control_ctx = device_control_ctx;
    mic_audio_pipeline_servicer_reg_ctx.device_control_ctx_count = 1;
    mic_audio_pipeline_servicer_reg_ctx.app_data =
        &mic_audio_pipeline_servicer_context;

    xTaskCreate(
        audio_pipeline_servicer,
        "audio mic ctrl",
        RTOS_THREAD_STACK_SIZE(audio_pipeline_servicer),
        &mic_audio_pipeline_servicer_reg_ctx,
        appconfDEVICE_CONTROL_SPI_PRIORITY,
        NULL
    );

    servicer_t dfu_servicer_ctx;
    dfu_servicer_init(&dfu_servicer_ctx);
    
    servicer_register_ctx_t dfu_servicer_reg_ctx = {
        &dfu_servicer_ctx,
        device_control_ctx,
        1,
        NULL
    };

    xTaskCreate(
        dfu_servicer,
        "dfu servicer",
        RTOS_THREAD_STACK_SIZE(dfu_servicer),
        &dfu_servicer_reg_ctx,
        appconfDEVICE_CONTROL_SPI_PRIORITY,
        NULL
    );

    xTaskCreate(
        device_control_ready_task,
        "dc ready",
        RTOS_THREAD_STACK_SIZE(device_control_ready_task),
        device_control_spi_ctx,
        appconfDEVICE_CONTROL_SPI_PRIORITY,
        NULL
    );
#endif

#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
    speaker_pipeline_settings_runtime_init(&speaker_pipeline_settings_runtime);
    mic_input_pipeline_settings_runtime_init(&mic_input_pipeline_settings_runtime);
    audio_pipeline_tile1_servicer_init(&speaker_audio_pipeline_servicer_state);

    speaker_audio_pipeline_servicer_context.servicer =
        &speaker_audio_pipeline_servicer_state;
    speaker_audio_pipeline_servicer_context.mic_output_settings = NULL;
    speaker_audio_pipeline_servicer_context.speaker_settings =
        &speaker_pipeline_settings_runtime;
    speaker_audio_pipeline_servicer_context.mic_input_settings =
        &mic_input_pipeline_settings_runtime;
    speaker_audio_pipeline_servicer_context.doa = NULL;

    speaker_audio_pipeline_servicer_reg_ctx.servicer =
        &speaker_audio_pipeline_servicer_state;
    speaker_audio_pipeline_servicer_reg_ctx.device_control_ctx = device_control_ctx;
    speaker_audio_pipeline_servicer_reg_ctx.device_control_ctx_count = 1;
    speaker_audio_pipeline_servicer_reg_ctx.app_data =
        &speaker_audio_pipeline_servicer_context;

    xTaskCreate(
        audio_pipeline_servicer,
        "audio spk ctrl",
        RTOS_THREAD_STACK_SIZE(audio_pipeline_servicer),
        &speaker_audio_pipeline_servicer_reg_ctx,
        appconfDEVICE_CONTROL_SPI_PRIORITY,
        NULL
    );
#endif

#if ON_TILE(WS2812_TILE_NO)
    servicer_t servicer_led_ring;
    led_ring_servicer_init(&servicer_led_ring);
    
    servicer_register_ctx_t led_ring_reg_ctx = {
        &servicer_led_ring,
        device_control_ctx,
        1,
        ws2812_ctx
    };
    
    xTaskCreate(
        led_ring_servicer,
        "LED-Ring servicer",
        RTOS_THREAD_STACK_SIZE(led_ring_servicer),
        &led_ring_reg_ctx,
        appconfDEVICE_CONTROL_SPI_PRIORITY,
        NULL
    );
#endif

#endif


#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
    ref_input_queue = &ref_input_queue_ctx;
    mic_input_sim_queue = &mic_input_sim_queue_ctx;
    ref_input_free_queue = &ref_input_free_queue_ctx;
    mic_input_sim_free_queue = &mic_input_sim_free_queue_ctx;
    xassert(rtos_osal_queue_create(ref_input_queue, NULL, 2, sizeof(void *)) ==
            RTOS_OSAL_SUCCESS);
    xassert(rtos_osal_queue_create(mic_input_sim_queue, NULL, 2, sizeof(void *)) ==
            RTOS_OSAL_SUCCESS);
    xassert(rtos_osal_queue_create(ref_input_free_queue,
                                   NULL,
                                   AUDIO_FRAME_POOL_DEPTH,
                                   sizeof(void *)) == RTOS_OSAL_SUCCESS);
    xassert(rtos_osal_queue_create(mic_input_sim_free_queue,
                                   NULL,
                                   AUDIO_FRAME_POOL_DEPTH,
                                   sizeof(void *)) == RTOS_OSAL_SUCCESS);

    for (size_t i = 0; i < AUDIO_FRAME_POOL_DEPTH; i++) {
        void *ref_slot = &ref_input_frame_pool[i][0][0];
        void *mic_slot = &mic_input_sim_frame_pool[i][0][0];
        xassert(rtos_osal_queue_send(ref_input_free_queue,
                                     &ref_slot,
                                     RTOS_OSAL_NO_WAIT) == RTOS_OSAL_SUCCESS);
        xassert(rtos_osal_queue_send(mic_input_sim_free_queue,
                                     &mic_slot,
                                     RTOS_OSAL_NO_WAIT) == RTOS_OSAL_SUCCESS);
    }
    speaker_pipeline_init(NULL, NULL);
#endif

    audio_pipeline_init(NULL, NULL);
    
    init_watchdog();

    mem_analysis();
}

void vApplicationMinimalIdleHook(void)
{
    rtos_printf("idle hook on tile %d core %d\n", THIS_XCORE_TILE, rtos_core_id_get());
    asm volatile("waiteu");
}

static void tile_common_init(chanend_t c)
{
    platform_init(c);
    chanend_free(c);

#if appconfUSB_AUDIO_ENABLED && ON_TILE(USB_TILE_NO)
    usb_audio_init(intertile_usb_audio_ctx, appconfUSB_AUDIO_TASK_PRIORITY);
#endif

    xTaskCreate((TaskFunction_t) startup_task,
                "startup_task",
                RTOS_THREAD_STACK_SIZE(startup_task),
                NULL,
                appconfSTARTUP_TASK_PRIORITY,
                NULL);

    rtos_printf("start scheduler on tile %d\n", THIS_XCORE_TILE);
    vTaskStartScheduler();
}

#if ON_TILE(0)
void main_tile0(chanend_t c0, chanend_t c1, chanend_t c2, chanend_t c3)
{
    (void) c0;
    (void) c2;
    (void) c3;

    tile_common_init(c1);
}
#endif

#if ON_TILE(1)
void main_tile1(chanend_t c0, chanend_t c1, chanend_t c2, chanend_t c3)
{
    (void) c1;
    (void) c2;
    (void) c3;

    tile_common_init(c0);
}
#endif
