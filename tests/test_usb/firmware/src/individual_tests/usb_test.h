// Copyright 2021-2023 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

#ifndef USB_TEST_H_
#define USB_TEST_H_

#include "rtos_test_utils.h"
#include "rtos_usb.h"

#define usb_printf( FMT, ... )      module_printf("USB", FMT, ##__VA_ARGS__)

#define USB_MAX_TESTS               4

#define USB_MAIN_TEST_ATTR          __attribute__((fptrgroup("rtos_test_usb_main_test_fptr_grp")))

/* Flags which may be set by a test to indicate a USB function is working,
 * this allows other tests that may be dependent on such functionality to skip
 * being tested if required functionality has not passed verification. */
#define USB_SOF_RECEIVED_FLAG       1
#define USB_MOUNTED_FLAG            2
#define USB_BULK_TRANSFER_FLAG      4
#define USB_CTRL_TRANSFER_FLAG      8

typedef struct usb_test_ctx usb_test_ctx_t;

struct usb_test_ctx {
    uint32_t flags;
    uint32_t cur_test;
    uint32_t test_cnt;
    char *name[USB_MAX_TESTS];

    USB_MAIN_TEST_ATTR int (*main_test[USB_MAX_TESTS])(usb_test_ctx_t *ctx);
};

typedef int (*usb_main_test_t)(usb_test_ctx_t *ctx);

int usb_device_tests(chanend_t c);

#endif /* USB_TEST_H_ */
