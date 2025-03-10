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
#include "individual_tests/local/usb_dfu_test.h"
#include "usb_descriptors.h"

#include "app_conf.h"

static const char *test_name = "dfu_test";

#define LOCAL_PRINTF(FMT, ...) usb_printf("%s|" FMT, test_name, ##__VA_ARGS__)

/*
 * This test application allows for host-side validation of the USB driver
 * by the use of DFU operations using "dfu-util". This application should
 * continue to run until one of the following holds true:
 * - Received the DFU detach command.
 * - Received DFU abort
 * - Timeout period elapsed while waiting for first transfer.
 * - Timeout period elapsed while waiting for subsequent transfers.
 *
 * Test firmware files must not exceed a length of MAX_PARTITION_SIZE.
 *
 */

#if ON_TILE(0)

#define NUM_PARITIONS       ALT_COUNT
#define MAX_PARTITION_SIZE  1024

static TimerHandle_t test_timeout_ctx = NULL;
static bool dfu_first_xfer = true;
static bool dfu_timeout = false;
static bool dfu_detach = false;
static bool dfu_abort = false;

static char test_images[NUM_PARITIONS][MAX_PARTITION_SIZE] = {
    "Partition 0 Test Data: The quick brown fox jumps over the lazy dog.",
    "Partition 1 Test Data: The quick brown fox jumps over the lazy dog.",
    "Partition 2 Test Data: The quick brown fox jumps over the lazy dog.",
};

static void timeout_cb(TimerHandle_t xTimer)
{
    LOCAL_PRINTF("Timeout");
    dfu_timeout = true;
}

static void timeout_handler(void) {
    if (dfu_first_xfer) {
        dfu_first_xfer = false;
        xTimerStop(test_timeout_ctx, 0);
        xTimerChangePeriod(test_timeout_ctx, pdMS_TO_TICKS(DFU_NEXT_XFER_TIMEOUT_MS), 0);
    }

    xTimerReset(test_timeout_ctx, 0);
}

//--------------------------------------------------------------------+
// DFU callbacks
//--------------------------------------------------------------------+

uint32_t tud_dfu_get_timeout_cb(uint8_t alt, uint8_t state)
{
    LOCAL_PRINTF("tud_dfu_get_timeout_cb: alt=%u, state=%u", alt, state);

    if (state == DFU_DNBUSY) {
        return (alt == 0) ? 1 : 100;
    } else if (state == DFU_MANIFEST) {
        return 0;
    }

    return 0;
}

void tud_dfu_download_cb(uint8_t alt, uint16_t block_num, uint8_t const *data,
                         uint16_t length)
{
    LOCAL_PRINTF("tud_dfu_download_cb: alt=%u, block_num=%u, length=%u", alt,
                 block_num, length);

    timeout_handler();

    // Test logic needs to be adapted if these assertions fail.
    xassert(alt < NUM_PARITIONS);
    xassert(length <= MAX_PARTITION_SIZE);

    uint32_t start_offset = block_num * CFG_TUD_DFU_XFER_BUFSIZE;
    for (uint16_t i = 0; i < length; i++) {
        test_images[alt][start_offset + i] = data[i];
    }

    tud_dfu_finish_flashing(DFU_STATUS_OK);
}

void tud_dfu_manifest_cb(uint8_t alt)
{
    LOCAL_PRINTF("tud_dfu_manifest_cb: alt=%u", alt);
    tud_dfu_finish_flashing(DFU_STATUS_OK);
}

uint16_t tud_dfu_upload_cb(uint8_t alt, uint16_t block_num, uint8_t *data,
                           uint16_t length)
{
    LOCAL_PRINTF("tud_dfu_upload_cb: alt=%u, block_num=%u, length=%u - request",
                 alt, block_num, length);

    timeout_handler();

    uint32_t start_offset = block_num * CFG_TUD_DFU_XFER_BUFSIZE;
    uint32_t end_of_partition_offset = MAX_PARTITION_SIZE - start_offset;

    // Test logic needs to be adapted if this assertion fails.
    xassert(start_offset <= MAX_PARTITION_SIZE);

    uint16_t xfer_len = (uint16_t)strnlen(&test_images[alt][start_offset],
                                          end_of_partition_offset);
    if (xfer_len > length) {
        xfer_len = length;
    }

    memcpy(data, &test_images[alt][start_offset], xfer_len);

    LOCAL_PRINTF("tud_dfu_upload_cb: alt=%u, block_num=%u, length=%u - response",
                 alt, block_num, xfer_len);
    return xfer_len;
}

void tud_dfu_abort_cb(uint8_t alt)
{
    LOCAL_PRINTF("tud_dfu_abort_cb: alt=%u", alt);
    dfu_abort = true;
}

void tud_dfu_detach_cb(void)
{
    LOCAL_PRINTF("tud_dfu_detach_cb");
    dfu_detach = true;
}

#endif /* ON_TILE(0) */

//--------------------------------------------------------------------+
// Main test functions
//--------------------------------------------------------------------+

USB_MAIN_TEST_ATTR
static int dfu_test(usb_test_ctx_t *ctx)
{
    int result = 0;

    LOCAL_PRINTF("Start");

#if ON_TILE(0)
    if ((ctx->flags & USB_MOUNTED_FLAG) == 0) {
        LOCAL_PRINTF("Skipped (not mounted)");
        result = 1;
    } else {
        test_timeout_ctx = xTimerCreate("test_tmo",
                                        pdMS_TO_TICKS(DFU_FIRST_XFER_TIMEOUT_MS),
                                        pdFALSE,
                                        NULL,
                                        timeout_cb);

        xTimerStart(test_timeout_ctx, 0);

        while (1) {
            vTaskDelay(pdMS_TO_TICKS(1));

            if (dfu_detach || dfu_timeout || dfu_abort) {
                break;
            }
        }

        xTimerStop(test_timeout_ctx, 0);
        xTimerDelete(test_timeout_ctx, 0);
    }
#endif

    LOCAL_PRINTF("Done");

#if ON_TILE(0)
    if (dfu_detach) {
        ctx->flags |= USB_CTRL_TRANSFER_FLAG;
    } else {
        result = 1;
    }
#endif

    return result;
}

void register_dfu_test(usb_test_ctx_t *test_ctx)
{
    uint32_t this_test_num = test_ctx->test_cnt;

    LOCAL_PRINTF("Register to test num %d", this_test_num);

    test_ctx->name[this_test_num] = (char *)test_name;
    test_ctx->main_test[this_test_num] = dfu_test;

    test_ctx->test_cnt++;
}
