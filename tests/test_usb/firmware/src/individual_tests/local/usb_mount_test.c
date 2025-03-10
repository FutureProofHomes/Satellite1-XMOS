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
#include "individual_tests/local/usb_mount_test.h"
#include "usb_descriptors.h"

#include "app_conf.h"

static const char *test_name = "mount_test";

#define LOCAL_PRINTF(FMT, ...) usb_printf("%s|" FMT, test_name, ##__VA_ARGS__)

/*
 * This test validates that the USB mount callback is called. This is a
 * fundamental indicator of a working USB implementation, if this test does not
 * pass no USB class functionality will work.
 */

#if ON_TILE(0)

static TimerHandle_t test_timeout_ctx = NULL;
static int mounted = false;
static bool mount_timeout = false;

static void timeout_cb(TimerHandle_t xTimer)
{
    mount_timeout = true;
    LOCAL_PRINTF("Timeout");
}

void tud_mount_cb(void)
{
    mounted = true;
    LOCAL_PRINTF("tud_mount_cb");
}

#endif /* ON_TILE(0) */

//--------------------------------------------------------------------+
// Main test functions
//--------------------------------------------------------------------+

USB_MAIN_TEST_ATTR
static int mount_test(usb_test_ctx_t *ctx)
{
    int result = 0;

    LOCAL_PRINTF("Start");

#if ON_TILE(0)
    test_timeout_ctx = xTimerCreate("test_tmo",
                                    pdMS_TO_TICKS(USB_MOUNT_TIMEOUT_MS),
                                    pdFALSE,
                                    NULL,
                                    timeout_cb);

    xTimerStart(test_timeout_ctx, 0);

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(1));

        // The test concludes when the device is mounted or the timeout event occurs.
        if (mounted || mount_timeout) {
            break;
        }
    }

    xTimerStop(test_timeout_ctx, 0);
    xTimerDelete(test_timeout_ctx, 0);
#endif

    LOCAL_PRINTF("Done");

#if ON_TILE(0)
    if (mounted) {
        ctx->flags |= USB_MOUNTED_FLAG;
    } else {
        result = 1;
    }
#endif

    return result;
}

void register_mount_test(usb_test_ctx_t *test_ctx)
{
    uint32_t this_test_num = test_ctx->test_cnt;

    LOCAL_PRINTF("Register to test num %d", this_test_num);

    test_ctx->name[this_test_num] = (char *)test_name;
    test_ctx->main_test[this_test_num] = mount_test;

    test_ctx->test_cnt++;
}