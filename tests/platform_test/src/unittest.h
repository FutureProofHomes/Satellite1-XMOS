#ifndef UNITTEST_H_
#define UNITTEST_H_

#include "rtos_printf.h"
#include "FreeRTOS.h"

//#include "rtos_usb.h"
#include "usb/usb_cdc.h"

#define module_printf( testname, FMT, ... )   rtos_printf( "Tile[%d]|FCore[%d]|%u|%s|" FMT "\n", THIS_XCORE_TILE, rtos_core_id_get(), 0, testname, ##__VA_ARGS__ )

#define test_printf( FMT, ... )      cdc_printf( "Tile[%d]|FCore[%d]|%u|%s|" FMT "\n", THIS_XCORE_TILE, rtos_core_id_get(), 0, "DUMMY", ##__VA_ARGS__ )

#define MAX_TESTS                  10

#define MAIN_TEST_ATTR            __attribute__((fptrgroup("rtos_test_main_test_fptr_grp")))

/* Flags which may be set by a test to indicate a USB function is working,
 * this allows other tests that may be dependent on such functionality to skip
 * being tested if required functionality has not passed verification. */
#define USB_SOF_RECEIVED_FLAG       1
#define USB_MOUNTED_FLAG            2
#define USB_BULK_TRANSFER_FLAG      4
#define USB_CTRL_TRANSFER_FLAG      8

typedef struct test_ctx test_ctx_t;

struct test_ctx {
    uint32_t flags;
    uint32_t cur_test;
    uint32_t test_cnt;
    char *name[MAX_TESTS];

    MAIN_TEST_ATTR int (*main_test[MAX_TESTS])(test_ctx_t *ctx);
};

typedef int (*main_test_t)(test_ctx_t *ctx);

//int run_tests(chanend_t c); // {return 0;}

#endif /* UNITTEST_H_ */