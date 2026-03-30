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
#include "audio_pipeline.h"
#include "speaker_pipeline.h"
#include "audio_runtime/audio_runtime_gain.h"
#include "audio_pipeline_control/audio_pipeline_control_servicer.h"
#include "dfu_servicer.h"
#include "gpio/gpio_servicer.h"
#include "control/device_control_servicer_config.h"
#include "control/audio_cfg_servicer.h"
#include "builtin_tests/spi_echo_servicer/spi_echo_servicer.h"

#if appconfUSB_ENABLED
#include "platform/usb/usb_support.h"
#include "platform/usb/usb_audio.h"
#include "platfrom/usb/usb_cdc.h"
#endif

#if appconfLED_RING
#include "led_ring/led_ring_servicer.h"
#endif

#include "gcc_phat.h"
#include "doa_led.h"
/* Config headers for sw_pll */
#include "sw_pll.h"

volatile int mic_from_usb = appconfMIC_SRC_DEFAULT;
volatile int aec_ref_source = appconfAEC_REF_DEFAULT;

#define DEVICE_STATUS_READY_REGISTER_IDX   0
#define DEVICE_STATUS_READY_VALUE          1

#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
DWORD_ALIGNED doa4_state_t doa;
#if appconfDEVICE_CTRL_SPI
static doa_runtime_t doa_runtime;
#endif
#endif

#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
rtos_osal_queue_t *ref_input_queue;
rtos_osal_queue_t *mic_input_sim_queue;
#if appconfDEVICE_CTRL_SPI
static servicer_t speaker_audio_pipeline_servicer_state;
static speaker_pipeline_settings_runtime_t speaker_pipeline_settings_runtime;
static mic_input_pipeline_settings_runtime_t mic_input_pipeline_settings_runtime;
static audio_pipeline_servicer_ctx_t speaker_audio_pipeline_servicer_context;
static servicer_register_ctx_t speaker_audio_pipeline_servicer_reg_ctx;
#endif
#endif

#if ON_TILE(0)
#if appconfDEVICE_CTRL_SPI
static servicer_t mic_audio_pipeline_servicer_state;
mic_output_pipeline_settings_runtime_t mic_output_pipeline_settings_runtime;
static audio_pipeline_servicer_ctx_t mic_audio_pipeline_servicer_context;
static servicer_register_ctx_t mic_audio_pipeline_servicer_reg_ctx;
#endif
#endif

#if ON_TILE(SPEAKER_PIPELINE_TILE_NO) && appconfDEVICE_CTRL_SPI
static void doa_runtime_update(doa_runtime_t *runtime,
                               const int32_t *doa_input,
                               size_t frame_count,
                               float raw_angle_rad,
                               float smooth_angle_rad)
{
    xassert(runtime != NULL);
    xassert(doa_input != NULL);

    runtime->raw.doa_mrad = (int32_t) (raw_angle_rad * 1000.0f);
    runtime->raw.seq++;
    runtime->raw.valid = 1;

    runtime->smooth.doa_mrad = (int32_t) (smooth_angle_rad * 1000.0f);
    runtime->smooth.seq++;
    runtime->smooth.valid = 1;

    runtime->mic_input_debug.frame_counter++;
    for (size_t ch = 0; ch < appconfMIC_PIPELINE_INPUT_CHANNELS; ch++) {
        uint64_t sum_abs = 0;
        for (size_t i = 0; i < frame_count; i++) {
            int64_t sample = doa_input[(ch * frame_count) + i];
            if (sample < 0) {
                sample = -sample;
            }
            sum_abs += (uint64_t)sample;
        }
        runtime->mic_input_debug.mic_mean_abs[ch] = (uint32_t)(sum_abs / frame_count);
    }
}
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

static void upsample_frame_repeat_x3(
    int32_t dst[appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE][appconfAUDIO_SPK_CHANNELS],
    const int32_t src[appconfAUDIO_PIPELINE_FRAME_ADVANCE][appconfMIC_PIPELINE_REF_CHANNELS])
{
    for (size_t frame = 0; frame < appconfAUDIO_PIPELINE_FRAME_ADVANCE; frame++) {
        size_t out = frame * 3;
        int32_t l = src[frame][0];
        int32_t r = src[frame][1];

        dst[out][0] = l;
        dst[out][1] = r;
        dst[out + 1][0] = l;
        dst[out + 1][1] = r;
        dst[out + 2][0] = l;
        dst[out + 2][1] = r;
    }
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
    if (true) {
        /*
        * As noted above, this does not block.
        * and expects ref L, ref R, mic 0, mic 1
        */
        usb_audio_recv(intertile_usb_audio_ctx,
            frame_count,
            input_audio_frames,
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
    mic_input_pipeline_settings_t default_mic_input_settings;
    mic_input_pipeline_settings_t *mic_input_settings = NULL;
    int32_t ref_frame_16k[appconfAUDIO_PIPELINE_FRAME_ADVANCE][appconfMIC_PIPELINE_REF_CHANNELS];

    xassert(frame_count == appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE);

#if appconfDEVICE_CTRL_SPI
    mic_input_settings = &mic_input_pipeline_settings_runtime.active;
#endif

    if (mic_input_settings == NULL) {
        mic_input_pipeline_settings_default(&default_mic_input_settings);
        mic_input_settings = &default_mic_input_settings;
    }

    if (appconfI2S_AUDIO_SAMPLE_RATE == 3 * appconfAUDIO_PIPELINE_SAMPLE_RATE) {
        packaged_ref_mode =
            mic_input_settings->ref_source_mode == AUDIO_PIPELINE_REF_SOURCE_PACKAGED_INPUT;
        packaged_mic_mode =
            mic_input_settings->mic_source_mode == AUDIO_PIPELINE_MIC_SOURCE_PACKAGED_INPUT;
    }
    
    /* I2S expects sample channel format */
    int32_t tmp[appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE][appconfAUDIO_SPK_CHANNELS];
    int32_t *tmpptr = (int32_t *)output_audio_frames;

    for (int j = 0; j < frame_count; j++) {
        tmp[j][0] = *(tmpptr + j + (0 * frame_count));
        tmp[j][1] = *(tmpptr + j + (1 * frame_count));
    }

    if (packaged_ref_mode) {
        for (size_t frame = 0; frame < appconfAUDIO_PIPELINE_FRAME_ADVANCE; frame++) {
            ref_frame_16k[frame][0] =
                get_packaged_lane_sample(tmpptr,
                                         frame_count,
                                         mic_input_settings->ref_input_channel_map[0],
                                         frame);
            ref_frame_16k[frame][1] =
                get_packaged_lane_sample(tmpptr,
                                         frame_count,
                                         mic_input_settings->ref_input_channel_map[1],
                                         frame);
        }

        upsample_frame_repeat_x3(tmp, ref_frame_16k);
    }
    
    // send to DAC
    rtos_i2s_tx_1(i2s_ctx,
                (int32_t*) tmp,
                frame_count,
                portMAX_DELAY);
    
    void *frame_data;
    frame_data = pvPortMalloc(appconfAUDIO_PIPELINE_FRAME_ADVANCE *
                              appconfMIC_PIPELINE_REF_CHANNELS * sizeof(int32_t));

    if (packaged_ref_mode) {
        memcpy(frame_data,
               ref_frame_16k,
               appconfAUDIO_PIPELINE_FRAME_ADVANCE * appconfMIC_PIPELINE_REF_CHANNELS *
                   sizeof(int32_t));
    } else if (appconfI2S_AUDIO_SAMPLE_RATE == 3 * appconfAUDIO_PIPELINE_SAMPLE_RATE) {
        static int64_t sum[2];
        static int32_t src_data[2][SRC_FF3V_FIR_NUM_PHASES][SRC_FF3V_FIR_TAPS_PER_PHASE]
            __attribute__((aligned(8)));
        int32_t tmp_out[appconfAUDIO_PIPELINE_FRAME_ADVANCE][appconfMIC_PIPELINE_REF_CHANNELS];

        for (int frame = 0; frame < frame_count; frame += 3) {
            sum[0] = src_ds3_voice_add_sample(0, src_data[0][0], src_ff3v_fir_coefs[0], tmp[frame][0]);
            sum[1] = src_ds3_voice_add_sample(0, src_data[1][0], src_ff3v_fir_coefs[0], tmp[frame][1]);

            sum[0] = src_ds3_voice_add_sample(sum[0], src_data[0][1], src_ff3v_fir_coefs[1], tmp[frame+1][0]);
            sum[1] = src_ds3_voice_add_sample(sum[1], src_data[1][1], src_ff3v_fir_coefs[1], tmp[frame+1][1]);

            tmp_out[frame/3][0] = src_ds3_voice_add_final_sample(sum[0], src_data[0][2], src_ff3v_fir_coefs[2], tmp[frame+2][0]);
            tmp_out[frame/3][1] = src_ds3_voice_add_final_sample(sum[1], src_data[1][2], src_ff3v_fir_coefs[2], tmp[frame+2][1]);
        }
        memcpy(frame_data,
               tmp_out,
               appconfAUDIO_PIPELINE_FRAME_ADVANCE * appconfMIC_PIPELINE_REF_CHANNELS *
                   sizeof(int32_t));
    } else {
      memcpy(frame_data,
             tmp,
             appconfAUDIO_PIPELINE_FRAME_ADVANCE * appconfMIC_PIPELINE_REF_CHANNELS *
                 sizeof(int32_t));
    }
    
    // send to microphone pipeline as reference
    (void) rtos_osal_queue_send(ref_input_queue, &frame_data, RTOS_OSAL_WAIT_FOREVER);

    if (packaged_mic_mode) {
        void *mic_frame_data =
            pvPortMalloc(appconfAUDIO_PIPELINE_FRAME_ADVANCE *
                         appconfMIC_PIPELINE_INPUT_CHANNELS * sizeof(int32_t));
        int32_t *mic_dst = (int32_t *)mic_frame_data;

        xassert(appconfMIC_PIPELINE_INPUT_CHANNELS ==
                AUDIO_PIPELINE_MIC_INPUT_CHANNEL_MAP_COUNT);
        for (size_t mic_ch = 0; mic_ch < appconfMIC_PIPELINE_INPUT_CHANNELS; mic_ch++) {
            for (size_t frame = 0; frame < appconfAUDIO_PIPELINE_FRAME_ADVANCE; frame++) {
                *(mic_dst + (mic_ch * appconfAUDIO_PIPELINE_FRAME_ADVANCE) + frame) =
                    get_packaged_lane_sample(tmpptr,
                                             frame_count,
                                             mic_input_settings->mic_input_channel_map[mic_ch],
                                             frame);
            }
        }

        (void) rtos_osal_queue_send(mic_input_sim_queue,
                                    &mic_frame_data,
                                    RTOS_OSAL_WAIT_FOREVER);
    }

#endif
    return AUDIO_PIPELINE_FREE_FRAME;
}


void audio_pipeline_input(void *input_app_data,
                        int32_t* input_audio_frames,
                        size_t ch_count,
                        size_t frame_count)
{
    (void) input_app_data;
#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
    bool packaged_mic_mode = false;
    mic_input_pipeline_settings_t default_mic_input_settings;
    mic_input_pipeline_settings_t *mic_input_settings = NULL;
#endif
    int32_t *mic_data = (input_audio_frames + (appconfMIC_PIPELINE_REF_CHANNELS * frame_count));
    
    // odd usage of wrong cast types in the rtos library
    int32_t **mic_ptr = (int32_t **) mic_data;

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
    (void) rtos_osal_queue_receive(ref_input_queue, &frame_data, RTOS_OSAL_WAIT_FOREVER);
    int32_t *tmpptr = (int32_t *)input_audio_frames;
    int32_t *refptr = (int32_t *)frame_data;

    for (int i=0; i<frame_count; i++) {
        /* ref is first */
        *(tmpptr + i) = *(refptr++);
        *(tmpptr + i + frame_count) = *(refptr++);
    }

    rtos_osal_free(frame_data);
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

        (void) rtos_osal_queue_receive(mic_input_sim_queue,
                                       &sim_mic_frame_data,
                                       RTOS_OSAL_WAIT_FOREVER);
        memcpy(mic_data,
               sim_mic_frame_data,
               appconfAUDIO_PIPELINE_FRAME_ADVANCE *
                   appconfMIC_PIPELINE_INPUT_CHANNELS * sizeof(int32_t));
        rtos_osal_free(sim_mic_frame_data);
    }
#endif

#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
    const int32_t *doa_input = mic_data;
    float ang = doa4_process_frame(&doa, doa_input, -31);
    static float doa_smooth_ux = 1.0f;
    static float doa_smooth_uy = 0.0f;
    const float doa_alpha = 0.2f;
    float doa_newx = cosf(ang);
    float doa_newy = sinf(ang);
    doa_smooth_ux = (1.0f - doa_alpha) * doa_smooth_ux + doa_alpha * doa_newx;
    doa_smooth_uy = (1.0f - doa_alpha) * doa_smooth_uy + doa_alpha * doa_newy;
    float ang_smooth = atan2f(doa_smooth_uy, doa_smooth_ux);

#if appconfDEVICE_CTRL_SPI
    doa_runtime_update(&doa_runtime, doa_input, frame_count, ang, ang_smooth);
#endif

#if appconfLED_RING
    static uint8_t led_buffer[LED_RING_NUM_LEDS * 3];
    led_ring_show_doa(
        led_buffer,
        LED_RING_NUM_LEDS,
        ang_smooth,
        /*led0_angle_offset_rad=*/0.0f,
        /*led_index_offset=*/0,
        /*brightness=*/64
    );

    rtos_ws2812_write( ws2812_ctx, &led_buffer );
#else
#if configENABLE_DEBUG_PRINTF
    static uint32_t doa_print_decim = 0;
    doa_print_decim++;
    if ((doa_print_decim % 100U) == 0U) {
        int32_t doa_mrad = (int32_t)(ang * 1000.0f);
        rtos_printf("DoA angle mrad=%ld\n", (long)doa_mrad);
    }
#else
    (void) ang;
#endif
#endif
#endif

#if ON_TILE(SPEAKER_PIPELINE_TILE_NO) && appconfDEVICE_CTRL_SPI
    if (mic_input_settings == NULL) {
        mic_input_settings = &mic_input_pipeline_settings_runtime.active;
    }

    audio_runtime_apply_input_gains_q30(input_audio_frames,
                                        frame_count,
                                        appconfMIC_PIPELINE_REF_CHANNELS,
                                        appconfMIC_PIPELINE_INPUT_CHANNELS,
                                        mic_input_settings->ref_gain,
                                        mic_input_settings->mic_gain);
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

    xassert(frame_count == appconfAUDIO_PIPELINE_FRAME_ADVANCE);
    /* I2S expects sample channel format */
    int32_t tmp[appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE][appconfMIC_PIPELINE_OUT_CHANNELS];
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
    pack_extra_upsample_channels =
        mic_settings->pack_extra_upsample_channels;
     
     // 0 : proc 0, AEC+IC+NS+AGC audio
     // 1 : proc 1, mic 1 audio with AEC applied
     // 2 : ref 0, (overwritten by AEC+IC output)
     // 3 : ref 1, (overwritten by AEC+IC+NS output)
     // 4 : mic 0
     // 5 : mic 1
     // 6 : mic 2
     // 7 : mic 3

    if (appconfI2S_AUDIO_SAMPLE_RATE == 3*appconfAUDIO_PIPELINE_SAMPLE_RATE) {
        for (int in_frame = 0, out_frame = 0;
             in_frame < frame_count;
             in_frame++, out_frame += 3) {
            if (pack_extra_upsample_channels) {
                tmp[out_frame][0] =
                    *(tmpptr + in_frame + (upsample_channel_map[0] * frame_count));
                tmp[out_frame][1] =
                    *(tmpptr + in_frame + (upsample_channel_map[1] * frame_count));
                tmp[out_frame + 1][0] =
                    *(tmpptr + in_frame + (upsample_channel_map[2] * frame_count));
                tmp[out_frame + 1][1] =
                    *(tmpptr + in_frame + (upsample_channel_map[3] * frame_count));
                tmp[out_frame + 2][0] =
                    *(tmpptr + in_frame + (upsample_channel_map[4] * frame_count));
                tmp[out_frame + 2][1] =
                    *(tmpptr + in_frame + (upsample_channel_map[5] * frame_count));
            } else {
                int32_t smpl_ch0 =
                    *(tmpptr + in_frame + (i2s_channel_map[0] * frame_count));
                int32_t smpl_ch1 =
                    *(tmpptr + in_frame + (i2s_channel_map[1] * frame_count));

                tmp[out_frame][0] = smpl_ch0;
                tmp[out_frame][1] = smpl_ch1;
                tmp[out_frame + 1][0] = smpl_ch0;
                tmp[out_frame + 1][1] = smpl_ch1;
                tmp[out_frame + 2][0] = smpl_ch0;
                tmp[out_frame + 2][1] = smpl_ch1;
            }
        }
    } else {
        for (int j=0; j<frame_count; j++) {
            tmp[j][0] = *(tmpptr + j + (i2s_channel_map[0] * frame_count));
            tmp[j][1] = *(tmpptr + j + (i2s_channel_map[1] * frame_count));
        }
    }    
    
    
    rtos_i2s_tx(i2s_ctx,
                (int32_t*) tmp,
                appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE,
                portMAX_DELAY);
#endif

#if appconfUSB_AUDIO_ENABLED
    usb_audio_send(intertile_usb_audio_ctx,
                frame_count,
                output_audio_frames,
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

#if appconfWATCHDOG_ENABLED  
static void init_watchdog(void)
{
    //xin : 24 Mhz, decrement WATCHDOG_COUNT every 2.7 ms:
    write_sswitch_reg_no_ack(get_local_tile_id(), XS1_SSWITCH_WATCHDOG_PRESCALER_WRAP_NUM, (0xFFFF));
    //trigger watchdog after ~11s of inactivity    
    write_sswitch_reg_no_ack(get_local_tile_id(), XS1_SSWITCH_WATCHDOG_COUNT_NUM, 0xFFF );
    write_sswitch_reg_no_ack(get_local_tile_id(), XS1_SSWITCH_WATCHDOG_CFG_NUM, (1 << XS1_WATCHDOG_COUNT_ENABLE_SHIFT) | (1 << XS1_WATCHDOG_TRIGGER_ENABLE_SHIFT) );
}
#if ON_TILE(0)
static void reset_watchdog(void)
{
    //reset watchdog to max
    write_sswitch_reg_no_ack(get_local_tile_id(), XS1_SSWITCH_WATCHDOG_COUNT_NUM, 0xFFF );
}
#endif
#endif

static void mem_analysis(void)
{
	for (;;) {
		rtos_printf("Tile[%d]:\n\tMinimum heap free: %d\n\tCurrent heap free: %d\n", THIS_XCORE_TILE, xPortGetMinimumEverFreeHeapSize(), xPortGetFreeHeapSize());
#if appconfUSB_CDC_ENABLED        
        cdc_printf("Tile[%d]:\n\tMinimum heap free: %d\n\tCurrent heap free: %d\n", THIS_XCORE_TILE, xPortGetMinimumEverFreeHeapSize(), xPortGetFreeHeapSize());
#endif
#if ON_TILE(0) && appconfWATCHDOG_ENABLED         
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

#if ON_TILE(GPIO_SERVICER_NO)
    gpio_servicer_start(device_control_gpio_ctx, device_control_ctx, 1 );
#endif

#if ON_TILE(0)
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

    xTaskCreate(
        device_control_ready_task,
        "dc ready",
        RTOS_THREAD_STACK_SIZE(device_control_ready_task),
        device_control_spi_ctx,
        appconfDEVICE_CONTROL_SPI_PRIORITY,
        NULL
    );

#if appconfAUDIO_CFG_SERVICER_COMPAT_ENABLED
    /* Deprecated compatibility shim: use resid 230 (audio pipeline output settings). */
    static device_control_audio_cfg_ctx_t audio_cfg_ctx;
    audio_cfg_servicer_init(&audio_cfg_ctx, &mic_output_pipeline_settings_runtime);
    audio_cfg_servicer_start(&audio_cfg_ctx, device_control_ctx, 1);
#endif

#if BUILTIN_TESTS_SPI_ECHO_SERVICER
    static spi_echo_servicer_ctx_t echo_ctx;
    spi_echo_servicer_init(&echo_ctx);
    spi_echo_servicer_start(&echo_ctx, device_control_ctx, 1);
#endif    
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
#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
    speaker_audio_pipeline_servicer_context.doa = &doa_runtime;
#else
    speaker_audio_pipeline_servicer_context.doa = NULL;
#endif

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
#if ON_TILE(SPI_CLIENT_TILE_NO)    
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
#endif
#if appconfLED_RING
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
#endif


#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
    ref_input_queue = rtos_osal_malloc( sizeof(rtos_osal_queue_t) );
    rtos_osal_queue_create(ref_input_queue, NULL, 2, sizeof(void *));
    mic_input_sim_queue = rtos_osal_malloc(sizeof(rtos_osal_queue_t));
    rtos_osal_queue_create(mic_input_sim_queue, NULL, 2, sizeof(void *));
    speaker_pipeline_init(NULL, NULL);
#endif
#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
    doa4_init(&doa);
#endif

    audio_pipeline_init(NULL, NULL);
#if appconfWATCHDOG_ENABLED    
    init_watchdog();
#endif
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
