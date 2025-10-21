#pragma once

#if BUILTIN_TESTS_SPI_ECHO_SERVICER

#include "servicer.h"

#define SPI_ECHO_SERVICER_RESID (37)
#define SPI_ECHO_SERVICER_NUM_RESOURCES (1)


enum e_spi_echo_servicer_cmd_map {
  SPI_ECHO_SERVICER_CMD_SET = 10,
  SPI_ECHO_SERVICER_CMD_GET,
  NUM_SPI_ECHO_SERVICER_RESID_CMDS = 2
};



typedef struct {
    servicer_t  *servicer;
    device_control_t **device_control_ctx;
    size_t device_control_ctx_count;
} spi_echo_servicer_ctx_t;



void spi_echo_servicer_init(spi_echo_servicer_ctx_t *ctx);
void spi_echo_servicer_start(spi_echo_servicer_ctx_t *ctx, device_control_t **device_control_ctx, size_t device_control_ctx_count);

#endif