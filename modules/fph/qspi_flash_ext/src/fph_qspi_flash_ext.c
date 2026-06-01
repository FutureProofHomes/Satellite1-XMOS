#include "fph_qspi_flash_ext.h"

#include <limits.h>
#include <string.h>

/* FPH extension for command-style flash register reads not exposed by rtos_qspi_flash. */
extern int fl_command(
        unsigned int cmd,
        unsigned char input[],
        unsigned int num_in,
        unsigned char output[],
        unsigned int num_out);

void fph_qspi_flash_read_register(
        rtos_qspi_flash_t *ctx,
        uint8_t cmd,
        size_t dummy_bytes,
        uint8_t *data,
        size_t len)
{
    if ((ctx == NULL) || (data == NULL) || (len == 0)) {
        return;
    }

    if ((dummy_bytes > UINT_MAX) || (len > UINT_MAX)) {
        memset(data, 0, len);
        return;
    }

    unsigned char *dummy_buf = NULL;
    if (dummy_bytes > 0) {
        dummy_buf = rtos_osal_malloc(dummy_bytes);
        if (dummy_buf == NULL) {
            memset(data, 0, len);
            return;
        }
        memset(dummy_buf, 0, dummy_bytes);
    }

    rtos_qspi_flash_lock(ctx);
    int ret = fl_command((unsigned int) cmd,
                         dummy_buf,
                         (unsigned int) dummy_bytes,
                         data,
                         (unsigned int) len);
    rtos_qspi_flash_unlock(ctx);

    if (ret != 0) {
        memset(data, 0, len);
    }

    if (dummy_buf != NULL) {
        rtos_osal_free(dummy_buf);
    }
}
