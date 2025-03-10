// Copyright 2023 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

#include <stdlib.h>
#include <stdio.h>
#include <stdbool.h>
#include <string.h>

#include <xcore/assert.h>

#include "FreeRTOS.h"
#include "tusb.h"
#include "individual_tests/usb_test.h"
#include "individual_tests/local/usb_sof_test.h"
#include "usb_descriptors.h"

#include "app_conf.h"

static const char *test_name = "sof_test";

#define LOCAL_PRINTF(FMT, ...) usb_printf("%s|" FMT, test_name, ##__VA_ARGS__)

/*
 * This test validates the generation of start-of-frame callbacks from the
 * RTOS driver. The test will fail if no SOFs are received within the configured
 * time period specified by, SOF_TIMEOUT_MS.
 */

#if ON_TILE(0)

static TimerHandle_t test_timeout_ctx = NULL;
static int received_sof_event = true; // This will be set false, on entry of the test.
static bool sof_timeout = false;

static void timeout_cb(TimerHandle_t xTimer)
{
    LOCAL_PRINTF("Timeout");
    sof_timeout = true;
}

bool tud_xcore_sof_cb(uint8_t rhport, uint32_t cur_time)
{
    (void)cur_time;
    if (!received_sof_event) {
        received_sof_event = true;
        LOCAL_PRINTF("tud_xcore_sof_cb");
    }

    /* False tells TinyUSB to not send the SOF event to the stack */
    return false;
}

#endif /* ON_TILE(0) */

//--------------------------------------------------------------------+
// Main test functions
//--------------------------------------------------------------------+

USB_MAIN_TEST_ATTR
static int sof_test(usb_test_ctx_t *ctx)
{
    int result = 0;

    LOCAL_PRINTF("Start");

#if ON_TILE(0)
    test_timeout_ctx = xTimerCreate("test_tmo",
                                    pdMS_TO_TICKS(SOF_TIMEOUT_MS),
                                    pdFALSE,
                                    NULL,
                                    timeout_cb);

    xTimerStart(test_timeout_ctx, 0);
    received_sof_event = false;

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(1));

        // The test concludes when the SOF is received or when the timeout event occurs.
        if (received_sof_event || sof_timeout) {
            break;
        }
    }

    xTimerStop(test_timeout_ctx, 0);
    xTimerDelete(test_timeout_ctx, 0);
#endif

    LOCAL_PRINTF("Done");

#if ON_TILE(0)
    if (received_sof_event) {
        ctx->flags |= USB_SOF_RECEIVED_FLAG;
    } else {
        result = 1;
    }
#endif

    return result;
}

void register_sof_test(usb_test_ctx_t *test_ctx)
{
    uint32_t this_test_num = test_ctx->test_cnt;

    LOCAL_PRINTF("Register to test num %d", this_test_num);

    test_ctx->name[this_test_num] = (char *)test_name;
    test_ctx->main_test[this_test_num] = sof_test;

    test_ctx->test_cnt++;
}
