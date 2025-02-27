// Copyright 2021-2023 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

/* System headers */
#include <stdlib.h>
#include <platform.h>
#include <xs1.h>

/* FreeRTOS headers */
#include "FreeRTOS.h"
#include "task.h"

/* Library headers */
#include "rtos_intertile.h"
#include "usb_support.h"
#include "rtos_gpio.h"
//#include "src.h"

/* App headers */
#include "app_conf.h"
#include "platform/platform_conf.h"

#include "usb/usb_cdc.h"
#include "usb/usb_audio.h"
#include "unittest.h"

#include "platform/driver_instances.h"
#include "platform/platform_init.h"

#include "speaker_pipeline.h"
#include "audio_pipeline.h"


chanend_t other_tile_c;

#define kernel_printf( FMT, ... )    module_printf("KERNEL", FMT, ##__VA_ARGS__)

#ifndef TEST_NAME
#define TEST_NAME "BASE_TEST"
#endif

#ifndef RUN_TESTS
#define RUN_TESTS (1)
#endif

#if appconfUSE_SPK_PIPELINE_AS_REF
#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
rtos_osal_queue_t *ref_input_queue;
EventGroupHandle_t xEventBits;
#endif
#endif


#if BOARD_ID == BOARD_ID_SATELLITE1
int xscope_gettime( void )
{
     return xTaskGetTickCount();
}
#endif

void speaker_pipeline_input(void *input_app_data,
    int32_t **input_audio_frames,
    size_t ch_count,
    size_t frame_count)
{
#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
   
    if (false) { //!appconfUSB_ENABLED || audio_input_source == appconfAEC_REF_I2S) {
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

#if appconfUSB_AUDIO_ENABLED
        int32_t **usb_mic_audio_frame = NULL;
        if (true) {
            usb_mic_audio_frame = input_audio_frames;
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

#if appconfUSE_SPK_PIPELINE_AS_REF
    void* frame_data;
    frame_data = pvPortMalloc( appconfAUDIO_PIPELINE_FRAME_ADVANCE * appconfAUDIO_PIPELINE_CHANNELS * sizeof( int32_t ));

    // down sample reference signal to 16kHz if needed 
#if appconfAUDIO_SPK_PL_SR_FACTOR == 3
        static int64_t sum[2];
        static int32_t src_data[2][SRC_FF3V_FIR_NUM_PHASES][SRC_FF3V_FIR_TAPS_PER_PHASE] __attribute__((aligned (8)));        
        int32_t tmp_out[appconfAUDIO_PIPELINE_FRAME_ADVANCE][appconfAUDIO_PIPELINE_CHANNELS];    
        int32_t* in_ptr = (int32_t*)input_audio_frames;    
#if 0        
        for( int frame=0; frame < frame_count; frame +=3 ){
            sum[0] = src_ds3_voice_add_sample(0, src_data[0][0], src_ff3v_fir_coefs[0], *in_ptr);
            sum[1] = src_ds3_voice_add_sample(0, src_data[1][0], src_ff3v_fir_coefs[0], *(in_ptr+frame_count));
            in_ptr++;
            sum[0] = src_ds3_voice_add_sample(sum[0], src_data[0][1], src_ff3v_fir_coefs[1], *in_ptr);
            sum[1] = src_ds3_voice_add_sample(sum[1], src_data[1][1], src_ff3v_fir_coefs[1], *(in_ptr+frame_count));
            in_ptr++;
            tmp_out[frame/3][0] = src_ds3_voice_add_final_sample(sum[0], src_data[0][2], src_ff3v_fir_coefs[2], *in_ptr);
            tmp_out[frame/3][1] = src_ds3_voice_add_final_sample(sum[1], src_data[1][2], src_ff3v_fir_coefs[2], *(in_ptr+frame_count));
            in_ptr++;
        }
        memcpy( frame_data, tmp_out, appconfAUDIO_PIPELINE_FRAME_ADVANCE * appconfAUDIO_PIPELINE_CHANNELS * sizeof( int32_t ) );
#endif
#else
        int32_t *in_ptr  = (int32_t *)input_audio_frames;
        int32_t *out_ptr = (int32_t *)frame_data;
        for (int i=0; i<frame_count; i++) {
            /* ref is first */
            *out_ptr = *in_ptr;
            *(++out_ptr) = *(in_ptr+frame_count);
            in_ptr++;
            out_ptr++;
        }
#endif
    // send to microphone pipeline as reference
    //rtos_osal_free(frame_data);
    (void) rtos_osal_queue_send(ref_input_queue, &frame_data, RTOS_OSAL_WAIT_FOREVER);
#endif
#endif    
}


int speaker_pipeline_output(void *output_app_data,
    int32_t **output_audio_frames,
    size_t ch_count,
    size_t frame_count)
{
#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
    (void) output_app_data;
#if 1
    xassert(frame_count == appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE);

    /* I2S expects sample channel format */
    int32_t tmp[appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE][1][appconfAUDIO_PIPELINE_CHANNELS];
    int32_t *tmpptr = (int32_t *)output_audio_frames;
    for (int j=0; j<frame_count; j++) {
        tmp[j][0][0] = *(tmpptr+j+(0*frame_count));    // ref 0 -> DAC
        tmp[j][0][1] = *(tmpptr+j+(1*frame_count));    // ref 1 -> DAC
    }

    // send to DAC
    //rtos_i2s_tx_1(i2s_ctx,
    rtos_i2s_tx(i2s_ctx,
        (int32_t*) tmp,
        frame_count,
        portMAX_DELAY);
#endif
#endif
    return AUDIO_PIPELINE_FREE_FRAME;
}

#if 1
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
        received = rtos_mic_array_rx(
                        mic_array_ctx,
                        mic_ptr,
                        frame_count,
                        0);
        if (received == 0) {
            rtos_mic_array_rx(
                    mic_array_ctx,
                    mic_ptr,
                    frame_count,
                    portMAX_DELAY);
            flushed = 1;
        }
    }
#if appconfUSE_SPK_PIPELINE_AS_REF
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
#endif

    /*
    * NOTE: ALWAYS receive the next frame from the PDM mics,
    * even if USB is the current mic source. The controls the
    * timing since usb_audio_recv() does not block and will
    * receive all zeros if no frame is available yet.
    */
    rtos_mic_array_rx(
        mic_array_ctx,
        mic_ptr,
        frame_count,
        portMAX_DELAY
    );

}

int audio_pipeline_output(void *output_app_data,
    int32_t **output_audio_frames,
    size_t ch_count,
    size_t frame_count)
{
    (void) output_app_data;
#if ON_TILE(0)
    // 0 : proc 0, AEC+IC+NS+AGC audio
    // 1 : proc 1, mic 1 audio with AEC applied
    // 2 : ref 0, overwritten by AEC+IC output
    // 3 : ref 1, overwritten by AEC+IC+NS output
    // 4 : mic 0
    // 5 : mic 1
    xassert(frame_count == appconfAUDIO_PIPELINE_FRAME_ADVANCE);
        
#if appconfI2S_ENABLED && 0
#error "need to prepare tmp buffer for I2S"        
        rtos_i2s_tx(
            i2s_ctx,
            tmp,
            appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE,
            portMAX_DELAY
        );
#endif

#if appconfUSB_AUDIO_ENABLED && 1
        usb_audio_send(
            intertile_usb_audio_ctx,
            frame_count,
            output_audio_frames,
            6
        );
#endif

    return AUDIO_PIPELINE_FREE_FRAME;
#else
    xassert("Should not get called from Tile 1" == NULL);
    return 0;
#endif
}
#endif





void vApplicationMallocFailedHook( void )
{
    kernel_printf("Malloc Failed!");
    configASSERT(0);
}

void vApplicationStackOverflowHook( TaskHandle_t pxTask, char* pcTaskName )
{
    kernel_printf("Stack Overflow! %s", pcTaskName);
    configASSERT(0);
}

void vApplicationMinimalIdleHook(void)
{
    rtos_printf("idle hook on tile %d core %d\n", THIS_XCORE_TILE, rtos_core_id_get());
    asm volatile("waiteu");
}


#if 0
static void print_task_stats(){
        
        uint32_t uxArraySize = uxTaskGetNumberOfTasks();
        if (uxArraySize > 0u) {
            TaskStatus_t *pxTaskStatusArray = pvPortMalloc(uxArraySize * sizeof(TaskStatus_t));
            test_printf("FreeRTOS Free/Total heap: %lu / %lu Tasks: %d\r\n", xPortGetFreeHeapSize(), configTOTAL_HEAP_SIZE, uxArraySize );
            if (pxTaskStatusArray != NULL) {
                // Generate raw status information about each task.
                uint32_t total_runtime = 0u;
                uxArraySize = uxTaskGetSystemState(pxTaskStatusArray, uxArraySize, &total_runtime);
                total_runtime /= 100UL * configNUM_CORES;
                const uint32_t max_mask = (1 << configNUM_CORES) -1;
                test_printf("Total runtime: %lu\r\n", total_runtime);
                if( total_runtime > 0){
                    test_printf("%-25s\%-10s%-10s%-10s%-10s\r\n", "Taskname", "CoreMask", "prio", "Watermark", "PPM use");
                    for (uint8_t x = 0u; x < uxArraySize; x++) {
                        uint32_t ulStatsAsPercentage = pxTaskStatusArray[ x ].ulRunTimeCounter / total_runtime;
                        const uint32_t core_aff = vTaskCoreAffinityGet(pxTaskStatusArray[x].xHandle);    
                        cdc_printf("%-25s\%-10u%-10lu%-10lu%-10lu\r\n",
                                pxTaskStatusArray[x].pcTaskName,
                                core_aff & max_mask,
                                pxTaskStatusArray[x].uxBasePriority,//uxTaskGetStackSize(pxTaskStatusArray[x].xHandle),
                                uxTaskGetStackHighWaterMark(pxTaskStatusArray[x].xHandle),
                                ulStatsAsPercentage);
                    } // end for
                }    
                vPortFree(pxTaskStatusArray);    
            }
        } // end if there are any tasks at all.. there will always be tasks
        // Now lets estimate the factor between the statistics timer and the freeRTOS tick
    
        uint32_t stats = 1; //RTOSGetRuntimeCounterValueFromISR();
        uint32_t tics = xTaskGetTickCount();
    
        if (stats > tics) {
            // as expected
            test_printf("Stats is %u, Tics %u. Stats is %u times faster\r\n",stats, tics, ((stats * 100u)/tics)/100u);
        }
        else {
            test_printf("Tics is %u, stats %u. Tics is %u times faster\r\n",tics, stats, ((tics * 100u)/stats)/100u);
    }
    
}
#endif



void vApplicationDaemonTaskStartup(void *arg)
{
#if appconfUSB_AUDIO_ENABLED
#if ON_TILE(USB_TILE_NO)
    //usb_audio_start();
#endif
#endif


    platform_test_start();

#if ON_TILE(0)
    rtos_gpio_port_id_t buttons = rtos_gpio_port(PORT_BUTTONS);
    rtos_gpio_port_enable(gpio_ctx_t0, buttons);
    rtos_gpio_port_pull_up(gpio_ctx_t0, buttons);
#endif

#if ON_TILE(SPEAKER_PIPELINE_TILE_NO)
#if appconfUSE_SPK_PIPELINE_AS_REF
    ref_input_queue = rtos_osal_malloc( sizeof(rtos_osal_queue_t) );
    rtos_osal_queue_create(ref_input_queue, NULL, 2, sizeof(void *));
#endif
    speaker_pipeline_init(NULL, NULL);
#endif

    audio_pipeline_init(NULL, NULL);

    while(1) { 
        
#if 0        
        if (RUN_TESTS) {
            if (run_tests(other_tile_c) != 0)
            {
                test_printf("FAIL %s", TEST_NAME);
            } else {
                test_printf("PASS %s", TEST_NAME);
            }
            
        } else {
            test_printf("SKIP %s", TEST_NAME);
        }
#endif    
#if ON_TILE(1)
        vTaskDelay(pdMS_TO_TICKS(2000));
#endif
        test_printf("Starting Loop...");
        for (;;) {
            //rtos_printf("\n\tMinimum heap free: %lu\n\tCurrent heap free: %lu\n", xPortGetMinimumEverFreeHeapSize(), xPortGetFreeHeapSize());

            test_printf("\n\tMinimum heap free: %lu\n\tCurrent heap free: %lu\n", xPortGetMinimumEverFreeHeapSize(), xPortGetFreeHeapSize());
#if 0            
            print_task_stats();
#endif
            vTaskDelay(5000);
        }
    }
    
    _Exit(0);

    chanend_free(other_tile_c);
    vTaskDelete(NULL);
}

#if ON_TILE(0)
void main_tile0(chanend_t c0, chanend_t c1, chanend_t c2, chanend_t c3)
{
    (void) c0;
    platform_test_init(c1);
#if appconfUSB_ENABLED
    usb_audio_init(intertile_usb_audio_ctx, appconfUSB_AUDIO_TASK_PRIORITY);
#endif

    (void) c2;
    (void) c3;

    other_tile_c = c1;

    
    xTaskCreate((TaskFunction_t) vApplicationDaemonTaskStartup,
                "ApplicationTask",
                RTOS_THREAD_STACK_SIZE(vApplicationDaemonTaskStartup),
                NULL,
                appconfSTARTUP_TASK_PRIORITY,
                NULL);

    printf("Start scheduler");
    vTaskStartScheduler();
    printf("Scheduler failed");

    return;
}
#endif /* ON_TILE(0) */

#if ON_TILE(1)
void main_tile1(chanend_t c0, chanend_t c1, chanend_t c2, chanend_t c3)
{
    platform_test_init(c0);
    (void) c1;
    (void) c2;
    (void) c3;

    other_tile_c = c0;

    xTaskCreate((TaskFunction_t) vApplicationDaemonTaskStartup,
                "ApplicationTask",
                RTOS_THREAD_STACK_SIZE(vApplicationDaemonTaskStartup),
                NULL,
                appconfSTARTUP_TASK_PRIORITY,
                NULL);

    printf("Start scheduler");
    vTaskStartScheduler();
    printf("Scheduler failed");

    return;
}
#endif /* ON_TILE(1) */
