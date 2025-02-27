#include "individual_tests/dummy_test.h"

#include "app_conf.h"

static const char *test_name = "dummy_test";

#define LOCAL_PRINTF(FMT, ...) test_printf("%s|" FMT, test_name, ##__VA_ARGS__)


MAIN_TEST_ATTR
static int dummy_test(test_ctx_t *ctx)
{
    int result = 0;

    LOCAL_PRINTF("Start");
    
    LOCAL_PRINTF("Running Dummy Test on Tile: %d", THIS_XCORE_TILE);

    LOCAL_PRINTF("Done");

    return result;
}


void register_dummy_test(test_ctx_t *test_ctx)
{
    uint32_t this_test_num = test_ctx->test_cnt;

    LOCAL_PRINTF("Register to test num %d", this_test_num);

    test_ctx->name[this_test_num] = (char *)test_name;
    test_ctx->main_test[this_test_num] = dummy_test;

    test_ctx->test_cnt++;
}
