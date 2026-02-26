// Copyright 2020-2024 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

#include <platform.h>
#include <xs1.h>
#include <xcore/channel.h>
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
#include "dfu_servicer.h"
#include "gpio/gpio_servicer.h"
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

#if ON_TILE(1)
DWORD_ALIGNED doa4_state_t doa;
#endif

#if ON_TILE(0)
rtos_osal_queue_t *cntrlChannelPipelineOut;
#endif


#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
rtos_osal_queue_t *ref_input_queue;
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
        // odd usage of double pointer cast
        usb_mic_audio_frame = (int32_t**) input_audio_frames;
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

    xassert(frame_count == appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE);
    
    /* I2S expects sample channel format */
    int32_t tmp[appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE][appconfAUDIO_SPK_CHANNELS];
    int32_t *tmpptr = (int32_t *)output_audio_frames;
    for (int j=0; j<frame_count; j++) {
        tmp[j][0] = *(tmpptr+j+(0*frame_count));    // ref 0 -> DAC
        tmp[j][1] = *(tmpptr+j+(1*frame_count));    // ref 1 -> DAC
    }
    
    // send to DAC
    rtos_i2s_tx_1(i2s_ctx,
                (int32_t*) tmp,
                frame_count,
                portMAX_DELAY);
    
    void* frame_data;
    frame_data = pvPortMalloc( appconfAUDIO_PIPELINE_FRAME_ADVANCE * appconfMIC_PIPELINE_REF_CHANNELS * sizeof( int32_t ));
    
    // down sample reference signal to 16kHz if needed 
    if (appconfI2S_AUDIO_SAMPLE_RATE == 3*appconfAUDIO_PIPELINE_SAMPLE_RATE) {
        static int64_t sum[2];
        static int32_t src_data[2][SRC_FF3V_FIR_NUM_PHASES][SRC_FF3V_FIR_TAPS_PER_PHASE] __attribute__((aligned (8)));
        int32_t tmp_out[appconfAUDIO_PIPELINE_FRAME_ADVANCE][appconfMIC_PIPELINE_REF_CHANNELS];    
        
        for( int frame=0; frame < frame_count; frame +=3 ){
            sum[0] = src_ds3_voice_add_sample(0, src_data[0][0], src_ff3v_fir_coefs[0], tmp[frame][0]);
            sum[1] = src_ds3_voice_add_sample(0, src_data[1][0], src_ff3v_fir_coefs[0], tmp[frame][1]);

            sum[0] = src_ds3_voice_add_sample(sum[0], src_data[0][1], src_ff3v_fir_coefs[1], tmp[frame+1][0]);
            sum[1] = src_ds3_voice_add_sample(sum[1], src_data[1][1], src_ff3v_fir_coefs[1], tmp[frame+1][1]);

            tmp_out[frame/3][0] = src_ds3_voice_add_final_sample(sum[0], src_data[0][2], src_ff3v_fir_coefs[2], tmp[frame+2][0]);
            tmp_out[frame/3][1] = src_ds3_voice_add_final_sample(sum[1], src_data[1][2], src_ff3v_fir_coefs[2], tmp[frame+2][1]);
        }
        memcpy( frame_data, tmp_out, appconfAUDIO_PIPELINE_FRAME_ADVANCE * appconfMIC_PIPELINE_REF_CHANNELS * sizeof( int32_t ) );
    } else {
      memcpy( frame_data, tmp, appconfAUDIO_PIPELINE_FRAME_ADVANCE * appconfMIC_PIPELINE_REF_CHANNELS * sizeof( int32_t ) );
    }
    
    // send to microphone pipeline as reference
    (void) rtos_osal_queue_send(ref_input_queue, &frame_data, RTOS_OSAL_WAIT_FOREVER);

#endif
    return AUDIO_PIPELINE_FREE_FRAME;
}


typedef struct {
  float ux;
  float uy;
  uint8_t inited;
} doa_ema_t;

// alpha in (0,1]. Smaller = more smoothing (slower)
static inline float doa_ema_update(doa_ema_t *s, float ang_rad, float alpha)
{
  float x = cosf(ang_rad);
  float y = sinf(ang_rad);

  if(!s->inited){
    s->ux = x;
    s->uy = y;
    s->inited = 1;
  } else {
    s->ux = (1.0f - alpha) * s->ux + alpha * x;
    s->uy = (1.0f - alpha) * s->uy + alpha * y;
  }

  // optional renormalize (helps long-term stability)
  float n = sqrtf(s->ux*s->ux + s->uy*s->uy);
  if(n > 1e-12f){ s->ux /= n; s->uy /= n; }

  return atan2f(s->uy, s->ux);
}

void audio_pipeline_input(void *input_app_data,
                        int32_t* input_audio_frames,
                        size_t ch_count,
                        size_t frame_count)
{
    (void) input_app_data;
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
#if ON_TILE(1)    
    float ang = doa4_process_frame(&doa, mic_ptr, -31);
    static uint8_t led_buffer[LED_RING_NUM_LEDS * 3];
    static float ux=1.0f, uy=0.0f;
    float newx = cosf(ang), newy = sinf(ang);
    float alpha = 0.2f; // 0..1 (higher = faster)
    ux = (1.0f-alpha)*ux + alpha*newx;
    uy = (1.0f-alpha)*uy + alpha*newy;
    float ang_smooth = atan2f(uy, ux);
    led_ring_show_doa(
        led_buffer,
        LED_RING_NUM_LEDS,
        ang_smooth,
        /*led0_angle_offset_rad=*/0.0f,
        /*led_index_offset=*/0,
        /*brightness=*/64
    );

    rtos_ws2812_write( ws2812_ctx, &led_buffer );
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

    xassert(frame_count == appconfAUDIO_PIPELINE_FRAME_ADVANCE);
    /* I2S expects sample channel format */
    int32_t tmp[appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE][appconfMIC_PIPELINE_OUT_CHANNELS];
    int32_t *tmpptr = (int32_t *)output_audio_frames;
     
     // 0 : proc 0, AEC+IC+NS+AGC audio
     // 1 : proc 1, mic 1 audio with AEC applied
     // 2 : ref 0, (overwritten by AEC+IC output)
     // 3 : ref 1, (overwritten by AEC+IC+NS output)
     // 4 : mic 0
     // 5 : mic 1
     // 6 : mic 2
     // 7 : mic 3

    static uint8_t channel_select[2] = {2, 3};
    (void) rtos_osal_queue_receive(cntrlChannelPipelineOut, &channel_select, RTOS_OSAL_PORT_NO_WAIT);
    
     
    if (appconfI2S_AUDIO_SAMPLE_RATE == 3*appconfAUDIO_PIPELINE_SAMPLE_RATE) {    
        // duplicate to 48kHz
        for( int in_frame=0, out_frame=0; in_frame < frame_count; in_frame++, out_frame += 3 ){    
            int32_t smpl_ch0 = *(tmpptr + in_frame + (channel_select[0] * frame_count));
            
            int32_t smpl_ch1 = *(tmpptr + in_frame + (channel_select[1] * frame_count));
            
            tmp[out_frame][0] = smpl_ch0;
            tmp[out_frame][1] = smpl_ch1;
            tmp[out_frame+1][0] = smpl_ch0;
            tmp[out_frame+1][1] = smpl_ch1;
            tmp[out_frame+2][0] = smpl_ch0;
            tmp[out_frame+2][1] = smpl_ch1;
        }
    } else {
        for (int j=0; j<frame_count; j++) {
            tmp[j][0] = *(tmpptr+j+(channel_select[0] * frame_count));
            tmp[j][1] = *(tmpptr+j+(channel_select[1] * frame_count));
        }
    }    
    
    
    rtos_i2s_tx(i2s_ctx,
                (int32_t*) tmp,
                appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE,
                portMAX_DELAY);
#endif

#if appconfUSB_AUDIO_ENABLED
    // odd usage of wrong ptr cast in usb library
    int32_t** double_ptr_cast = (int32_t**) output_audio_frames;   
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
    cntrlChannelPipelineOut = rtos_osal_malloc(sizeof(rtos_osal_queue_t));
    rtos_osal_queue_create(cntrlChannelPipelineOut, "chanQ", 1, sizeof(channel_sel_t));
    static device_control_audio_cfg_ctx_t audio_cfg_ctx;
    audio_cfg_servicer_init(&audio_cfg_ctx, cntrlChannelPipelineOut);
    audio_cfg_servicer_start(&audio_cfg_ctx, device_control_ctx, 1);

#if BUILTIN_TESTS_SPI_ECHO_SERVICER
    static spi_echo_servicer_ctx_t echo_ctx;
    spi_echo_servicer_init(&echo_ctx);
    spi_echo_servicer_start(&echo_ctx, device_control_ctx, 1);
#endif    
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
    speaker_pipeline_init(NULL, NULL);
#endif
#if ON_TILE(1)
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
