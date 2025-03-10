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
#include "individual_tests/local/usb_cdc_test.h"
#include "usb_descriptors.h"

#include "app_conf.h"

static const char *test_name = "cdc_test";

#define LOCAL_PRINTF(FMT, ...) usb_printf("%s|" FMT, test_name, ##__VA_ARGS__)

/*
 * This test helps to validate USB bulk transfer functionality. A host
 * application is to open the two CDC Virtual COM Ports and send data to one
 * COM port and receive it on the other; and then send the same quantity of
 * bytes on the other COM port.
 *
 * The test concludes when any of the following holds true:
 * - Bytes received on COM 0 and COM 1 match (must be non-0)
 * - No serial data is received within CDC_FIRST_BYTE_TIMEOUT_MS
 * - No serial data is received after first byte within CDC_NEXT_BYTE_TIMEOUT_MS
 */

#if ON_TILE(0)

static int32_t itf_rx_bytes[CFG_TUD_CDC] = { 0, 0 };
static TimerHandle_t test_timeout_ctx = NULL;
static bool rx_timeout = false;
static bool rx_first_byte = true;

static void timeout_cb(TimerHandle_t xTimer)
{
    LOCAL_PRINTF("Timeout");
    rx_timeout = true;
}

static void echo_serial_port(uint8_t itf, uint8_t buf[], uint32_t count)
{
    for (uint32_t i = 0; i < count; i++) {
        tud_cdc_n_write_char(itf, buf[i]);
    }

    tud_cdc_n_write_flush(itf);
}

#endif

//--------------------------------------------------------------------+
// Main test functions
//--------------------------------------------------------------------+

USB_MAIN_TEST_ATTR
static int cdc_test(usb_test_ctx_t *ctx)
{
    int result = 0;

    LOCAL_PRINTF("Start");

#if ON_TILE(0)
    bool test_complete = false;

    if ((ctx->flags & USB_MOUNTED_FLAG) == 0) {
        LOCAL_PRINTF("Skipped (not mounted)");
        result = 1;
    } else {
        test_timeout_ctx = xTimerCreate("test_tmo",
                                        pdMS_TO_TICKS(CDC_FIRST_BYTE_TIMEOUT_MS),
                                        pdFALSE,
                                        NULL,
                                        timeout_cb);

        xTimerStart(test_timeout_ctx, 0);

        while (1) {
            for (uint8_t itf = 0; itf < CFG_TUD_CDC; itf++) {
                if (tud_cdc_n_available(itf) == 0)
                    continue;

                uint8_t other_itf = (itf) ? 0 : 1;

                if (rx_first_byte) {
                    rx_first_byte = false;
                    xTimerStop(test_timeout_ctx, 0);
                    xTimerChangePeriod(test_timeout_ctx, pdMS_TO_TICKS(CDC_NEXT_BYTE_TIMEOUT_MS), 0);
                }

                xTimerReset(test_timeout_ctx, 0);

                uint8_t buf[512];
                uint32_t count = tud_cdc_n_read(itf, buf, sizeof(buf));

                itf_rx_bytes[itf] += count;

                // Echo back to other interface.
                echo_serial_port(other_itf, buf, count);
                LOCAL_PRINTF("tud_cdc_n_read: itf=%i, count=%d, total=%d", itf, count, itf_rx_bytes[itf]);

                if (itf_rx_bytes[0] > 0 && (itf_rx_bytes[0] == itf_rx_bytes[1])) {
                    test_complete = true;
                }
            }

            if (test_complete || rx_timeout) {
                break;
            }
        }

        xTimerStop(test_timeout_ctx, 0);
        xTimerDelete(test_timeout_ctx, 0);
    }
#endif

    LOCAL_PRINTF("Done");

#if ON_TILE(0)
    if (test_complete) {
        ctx->flags |= USB_BULK_TRANSFER_FLAG;
    } else {
        result = 1;
    }
#endif

    return result;
}

void register_cdc_test(usb_test_ctx_t *test_ctx)
{
    uint32_t this_test_num = test_ctx->test_cnt;

    LOCAL_PRINTF("Register to test num %d", this_test_num);

    test_ctx->name[this_test_num] = (char *)test_name;
    test_ctx->main_test[this_test_num] = cdc_test;

    test_ctx->test_cnt++;
}
