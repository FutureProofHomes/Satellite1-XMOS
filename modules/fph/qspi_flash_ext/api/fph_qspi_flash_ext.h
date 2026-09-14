#pragma once

#include <stddef.h>
#include <stdint.h>

#include "rtos_qspi_flash.h"

/**
 * Reads data from a command/register style QSPI flash transaction.
 *
 * This sends cmd, then dummy_bytes zero bytes, then reads len bytes into data.
 */
void fph_qspi_flash_read_register(
        rtos_qspi_flash_t *ctx,
        uint8_t cmd,
        size_t dummy_bytes,
        uint8_t *data,
        size_t len);
