// Copyright 2020-2024 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

#include <platform.h>
#include <xs1.h>
#include <xcore/channel.h>

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
#include "usb_support.h"
#include "usb_audio.h"
#include "audio_pipeline.h"
#include "speaker_pipeline.h"
#include "dfu_servicer.h"
#include "gpio/gpio_servicer.h"
#include "led_ring/led_ring_servicer.h"

/* Headers used for the WW intent engine */
#if appconfINTENT_ENABLED
#include "intent_engine.h"
#include "intent_handler.h"
#include "fs_support.h"
#include "gpi_ctrl.h"
#include "leds.h"
#endif


/* Config headers for sw_pll */
#include "sw_pll.h"

volatile int mic_from_usb = appconfMIC_SRC_DEFAULT;
volatile int aec_ref_source = appconfAEC_REF_DEFAULT;

#if appconfI2S_ENABLED

#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
rtos_osal_queue_t *ref_input_queue;
#endif

void speaker_pipeline_input(void *input_app_data,
                        int32_t **input_audio_frames,
                        size_t ch_count,
                        size_t frame_count)
{

    if (!appconfUSB_ENABLED || aec_ref_source == appconfAEC_REF_I2S) {
        /* This shouldn't need to block given it shares a clock with the PDM mics */

        xassert(frame_count == appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE);
        /* I2S provides sample channel format */
        int32_t tmp[appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE][appconfI2S_AUDIO_INPUTS][appconfAUDIO_PIPELINE_CHANNELS];
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
}

int speaker_pipeline_output(void *output_app_data,
                        int32_t **output_audio_frames,
                        size_t ch_count,
                        size_t frame_count)
{
    (void) output_app_data;

    xassert(frame_count == appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE);
    
    /* I2S expects sample channel format */
    int32_t tmp[appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE][1][appconfAUDIO_PIPELINE_CHANNELS];
    int32_t *tmpptr = (int32_t *)output_audio_frames;
    for (int j=0; j<frame_count; j++) {
        tmp[j][0][0] = *(tmpptr+j+(0*frame_count));    // ref 0 -> DAC
        tmp[j][0][1] = *(tmpptr+j+(1*frame_count));    // ref 1 -> DAC
    }

    // send to DAC
    rtos_i2s_tx_1(i2s_ctx,
                (int32_t*) tmp,
                frame_count,
                portMAX_DELAY);
    
#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
    void* frame_data;
    frame_data = pvPortMalloc( appconfAUDIO_PIPELINE_FRAME_ADVANCE * appconfAUDIO_PIPELINE_CHANNELS * sizeof( int32_t ));
    static int64_t sum[2];
    static int32_t src_data[2][SRC_FF3V_FIR_NUM_PHASES][SRC_FF3V_FIR_TAPS_PER_PHASE] __attribute__((aligned (8)));
    
    // down sample reference signal to 16kHz if needed 
    if (appconfI2S_AUDIO_SAMPLE_RATE == 3*appconfAUDIO_PIPELINE_SAMPLE_RATE) {
        int32_t tmp_out[appconfAUDIO_PIPELINE_FRAME_ADVANCE][1][appconfAUDIO_PIPELINE_CHANNELS];    
        
        for( int frame=0; frame < frame_count; frame +=3 ){
            sum[0] = src_ds3_voice_add_sample(0, src_data[0][0], src_ff3v_fir_coefs[0], tmp[frame][0][0]);
            sum[1] = src_ds3_voice_add_sample(0, src_data[1][0], src_ff3v_fir_coefs[0], tmp[frame][0][1]);

            sum[0] = src_ds3_voice_add_sample(sum[0], src_data[0][1], src_ff3v_fir_coefs[1], tmp[frame+1][0][0]);
            sum[1] = src_ds3_voice_add_sample(sum[1], src_data[1][1], src_ff3v_fir_coefs[1], tmp[frame+1][0][1]);

            tmp_out[frame/3][0][0] = src_ds3_voice_add_final_sample(sum[0], src_data[0][2], src_ff3v_fir_coefs[2], tmp[frame+2][0][0]);
            tmp_out[frame/3][0][1] = src_ds3_voice_add_final_sample(sum[1], src_data[1][2], src_ff3v_fir_coefs[2], tmp[frame+2][0][1]);
        }
        memcpy( frame_data, tmp_out, appconfAUDIO_PIPELINE_FRAME_ADVANCE * appconfAUDIO_PIPELINE_CHANNELS * sizeof( int32_t ) );
    } else {
      memcpy( frame_data, tmp, appconfAUDIO_PIPELINE_FRAME_ADVANCE * appconfAUDIO_PIPELINE_CHANNELS * sizeof( int32_t ) );
    }
    
    // send to microphone pipeline as reference
    (void) rtos_osal_queue_send(ref_input_queue, &frame_data, RTOS_OSAL_WAIT_FOREVER);
#endif
    return AUDIO_PIPELINE_FREE_FRAME;
}
#endif


void audio_pipeline_input(void *input_app_data,
                        int32_t **input_audio_frames,
                        size_t ch_count,
                        size_t frame_count)
{
    (void) input_app_data;
    int32_t **mic_ptr = (int32_t **)(input_audio_frames + (2 * frame_count));

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

#if appconfUSB_ENABLED 
    int32_t **usb_mic_audio_frame = NULL;
    size_t ch_cnt = 2;  /* ref frames */

    if (aec_ref_source == appconfAEC_REF_USB) {
        usb_mic_audio_frame = input_audio_frames;
    }

    if (mic_from_usb) {
        ch_cnt += 2;  /* mic frames */
    }

    /*
     * As noted above, this does not block.
     * and expects ref L, ref R, mic 0, mic 1
     */
    usb_audio_recv(intertile_usb_audio_ctx,
                   frame_count,
                   usb_mic_audio_frame,
                   ch_cnt);
#endif

}

int audio_pipeline_output(void *output_app_data,
                        int32_t **output_audio_frames,
                        size_t ch_count,
                        size_t frame_count)
{
    (void) output_app_data;


#if appconfI2S_ENABLED

    xassert(frame_count == appconfAUDIO_PIPELINE_FRAME_ADVANCE);
    /* I2S expects sample channel format */
    int32_t tmp[appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE][1][appconfAUDIO_PIPELINE_CHANNELS];
    int32_t *tmpptr = (int32_t *)output_audio_frames;

    if (appconfI2S_AUDIO_SAMPLE_RATE == 3*appconfAUDIO_PIPELINE_SAMPLE_RATE) {    
        // duplicate to 48kHz
        for( int in_frame=0, out_frame=0; in_frame < frame_count; in_frame++, out_frame += 3 ){
            int32_t smpl_ch0 = *(tmpptr + in_frame + (0 * frame_count));
            int32_t smpl_ch1 = *(tmpptr + in_frame + (1 * frame_count));
            tmp[out_frame][0][0] = smpl_ch0;
            tmp[out_frame][0][1] = smpl_ch1;
            tmp[out_frame+1][0][0] = smpl_ch0;
            tmp[out_frame+1][0][1] = smpl_ch1;
            tmp[out_frame+2][0][0] = smpl_ch0;
            tmp[out_frame+2][0][1] = smpl_ch1;
        }
    } else {
        for (int j=0; j<frame_count; j++) {
            tmp[j][0][0] = *(tmpptr+j+(0*frame_count));    // proc 0 -> ESP32
            tmp[j][0][1] = *(tmpptr+j+(1*frame_count));    // proc 1 -> ESP32
        }
    }    
    
    
    rtos_i2s_tx(i2s_ctx,
                (int32_t*) tmp,
                appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE,
                portMAX_DELAY);
#endif

#if appconfUSB_ENABLED
    usb_audio_send(intertile_usb_audio_ctx,
                frame_count,
                output_audio_frames,
                6);
#endif
#if appconfINTENT_ENABLED

    int32_t ww_samples[appconfAUDIO_PIPELINE_FRAME_ADVANCE];
    for (int j=0; j<appconfAUDIO_PIPELINE_FRAME_ADVANCE; j++) {
        /* ASR output is first */
        ww_samples[j] = (uint32_t) *(output_audio_frames+j);
    }

    intent_engine_sample_push(ww_samples,
                              frame_count);
#endif

    return AUDIO_PIPELINE_FREE_FRAME;
}




void vApplicationMallocFailedHook(void)
{
    rtos_printf("Malloc Failed on tile %d!\n", THIS_XCORE_TILE);
    xassert(0);
    for(;;);
}

static void mem_analysis(void)
{
	for (;;) {
		rtos_printf("Tile[%d]:\n\tMinimum heap free: %d\n\tCurrent heap free: %d\n", THIS_XCORE_TILE, xPortGetMinimumEverFreeHeapSize(), xPortGetFreeHeapSize());
		vTaskDelay(pdMS_TO_TICKS(5000));
	}
}

void startup_task(void *arg)
{
    rtos_printf("Startup task running from tile %d on core %d\n", THIS_XCORE_TILE, portGET_CORE_ID());
    platform_start();

#if appconfDEVICE_CTRL_SPI
    device_control_t *device_control_ctx[1] = {device_control_spi_ctx}; 

#if ON_TILE(0)
    servicer_t servicer_gpio;
    gpio_servicer_init(&servicer_gpio);
    
    servicer_register_ctx_t gpio_reg_ctx = {
        &servicer_gpio,
        device_control_ctx,
        1,
        gpio_ctx_t0
    };
    
    
    xTaskCreate(
        gpio_servicer,
        "GPIO servicer",
        RTOS_THREAD_STACK_SIZE(gpio_servicer),
        &gpio_reg_ctx,
        appconfDEVICE_CONTROL_SPI_PRIORITY,
        NULL
    );
#endif

#if ON_TILE(WS2812_TILE_NO)
    static uint8_t neo_pixel_buffer[12 * 3];
    memset( neo_pixel_buffer, 0, 12 * 3);
    rtos_ws2812_write( ws2812_ctx, neo_pixel_buffer);
    
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


#if appconfINTENT_ENABLED && ON_TILE(0)
    led_task_create(appconfLED_TASK_PRIORITY, NULL);
#endif

#if appconfINTENT_ENABLED && ON_TILE(1)
    gpio_gpi_init(gpio_ctx_t0);
#endif

#if appconfINTENT_ENABLED && ON_TILE(FS_TILE_NO)
    rtos_fatfs_init(qspi_flash_ctx);
    // Setup flash low-level mode
    //   NOTE: must call rtos_qspi_flash_fast_read_shutdown_ll to use non low-level mode calls
    rtos_qspi_flash_fast_read_setup_ll(qspi_flash_ctx);
#endif

#if appconfINTENT_ENABLED && ON_TILE(ASR_TILE_NO)
    QueueHandle_t q_intent = xQueueCreate(appconfINTENT_QUEUE_LEN, sizeof(int32_t));
    intent_handler_create(appconfINTENT_MODEL_RUNNER_TASK_PRIORITY, q_intent);
    intent_engine_create(appconfINTENT_MODEL_RUNNER_TASK_PRIORITY, q_intent);
#endif

#if appconfINTENT_ENABLED && !ON_TILE(ASR_TILE_NO)
    // Wait until the intent engine is initialized before starting the
    // audio pipeline.
    intent_engine_ready_sync();
#endif

#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
    ref_input_queue = rtos_osal_malloc( sizeof(rtos_osal_queue_t) );
    rtos_osal_queue_create(ref_input_queue, NULL, 2, sizeof(void *));
    speaker_pipeline_init(NULL, NULL);
#endif

    audio_pipeline_init(NULL, NULL);

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

#if appconfUSB_ENABLED && ON_TILE(USB_TILE_NO)
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
