// Copyright 2021-2023 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

/* System headers */
#include <platform.h>
#include <xs1.h>
#include <string.h>

/* FreeRTOS headers */
#include "FreeRTOS.h"

/* Library headers */
#include "rtos_usb.h"

/* App headers */
#include "app_conf.h"
#include "individual_tests/usb_test.h"
#include "individual_tests/local/usb_sof_test.h"
#include "individual_tests/local/usb_mount_test.h"
#include "individual_tests/local/usb_cdc_test.h"
#include "individual_tests/local/usb_dfu_test.h"
#include "usb_support.h"

//--------------------------------------------------------------------+
// Device callbacks
//--------------------------------------------------------------------+

void tud_umount_cb(void)
{
    usb_printf("tud_umount_cb");
}

void tud_suspend_cb(bool remote_wakeup_en)
{
    usb_printf("tud_suspend_cb: remote_wakeup_en=%u", (uint8_t)remote_wakeup_en);
}

void tud_resume_cb(void)
{
    usb_printf("tud_resume_cb");
}

//--------------------------------------------------------------------+
// Top-level test logic
//--------------------------------------------------------------------+

static int run_usb_tests(usb_test_ctx_t *test_ctx, chanend_t c)
{
    int retval = 0;

    do
    {
        sync(c);
        if (test_ctx->main_test[test_ctx->cur_test] != NULL)
        {
            USB_MAIN_TEST_ATTR usb_main_test_t fn;
            fn = test_ctx->main_test[test_ctx->cur_test];
            int tmp = fn(test_ctx);
            retval = (retval != -1) ? tmp : retval;
        } else {
            usb_printf("Missing main_test callback on test %d", test_ctx->cur_test);
            retval = -1;
        }
    } while (++test_ctx->cur_test < test_ctx->test_cnt);

    return retval;
}

static void start_usb_devices(usb_test_ctx_t *test_ctx)
{
    usb_printf("Device start");
#if ON_TILE(0)
    usb_manager_start(configMAX_PRIORITIES-1);
#endif
    usb_printf("Device setup done");
}

static void register_usb_tests(usb_test_ctx_t *test_ctx)
{
    // NOTE: The ordering of these tests ensure fundamental USB mechanisms work
    // prior to testing higher level mechanisms.
    register_sof_test(test_ctx);
    register_mount_test(test_ctx);
    register_cdc_test(test_ctx);
    register_dfu_test(test_ctx);
}

static void usb_init_tests(usb_test_ctx_t *test_ctx)
{
    memset(test_ctx, 0, sizeof(usb_test_ctx_t));

    test_ctx->cur_test = 0;
    test_ctx->test_cnt = 0;

    register_usb_tests(test_ctx);

    configASSERT(test_ctx->test_cnt <= USB_MAX_TESTS);
}

int usb_device_tests(chanend_t c)
{
    usb_test_ctx_t test_ctx;
    int res = 0;

    sync(c);
    usb_printf("Init test context");
    usb_init_tests(&test_ctx);
    usb_printf("Test context init");

    sync(c);
    usb_printf("Start devices");
    start_usb_devices(&test_ctx);
    usb_printf("Devices started");

    sync(c);
    usb_printf("Start tests");
    res = run_usb_tests(&test_ctx, c);

    sync(c);   // Sync before return
    return res;
}
