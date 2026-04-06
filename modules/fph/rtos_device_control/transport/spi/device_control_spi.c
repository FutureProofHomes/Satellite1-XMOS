// Copyright 2022-2023 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.
#include <platform.h>
#include <stdio.h>
#include <string.h>

#include "rtos_spi_slave.h"

#include "rtos_printf.h"
#include "device_control.h"

#define SPI_XFER_RX_SIZE (256)
#define SPI_XFER_TX_SIZE (256)
#define SPI_MAX_PAYLOAD_LEN (256 - 3)

static uint8_t spi_xfer_rx_buf[SPI_XFER_RX_SIZE];
static uint8_t spi_xfer_tx_buf[SPI_XFER_TX_SIZE];
static uint8_t spi_xfer_rx_default_buf[SPI_XFER_RX_SIZE];
static uint8_t spi_xfer_tx_default_buf[SPI_XFER_TX_SIZE];
static uint32_t spi_xfer_count;

RTOS_SPI_SLAVE_CALLBACK_ATTR
void device_control_spi_start_cb(rtos_spi_slave_t *ctx,
                                 device_control_t *device_control_ctx)
{
    spi_xfer_tx_default_buf[0] = CONTROL_COMMAND_IGNORED_IN_DEVICE; // Fill error code indicating packet dropped in device

    spi_slave_default_buf_xfer_ended_disable(ctx);
    spi_slave_xfer_prepare_default_buffers(ctx, spi_xfer_rx_default_buf, SPI_XFER_RX_SIZE, spi_xfer_tx_default_buf, SPI_XFER_TX_SIZE);
    memset( spi_xfer_tx_buf, 0, SPI_XFER_TX_SIZE);

    control_ret_t dc_ret;

    dc_ret = device_control_resources_register(device_control_ctx,
                                               pdMS_TO_TICKS(5000));

    if (dc_ret != CONTROL_SUCCESS) {
        //rtos_printf("Device control resources failed to register for SPI on tile %d\n", THIS_XCORE_TILE);
    } else {
        //rtos_printf("Device control resources registered for SPI on tile %d\n", THIS_XCORE_TILE);
    }
    xassert(dc_ret == CONTROL_SUCCESS);

    spi_xfer_tx_buf[0] = 1;
    spi_xfer_tx_buf[1] = CONTROL_SUCCESS;
    memset(&spi_xfer_tx_buf[2], 0, SPI_XFER_TX_SIZE - 2);
    if (device_control_ctx->status_buffer != NULL) {
        memcpy(&spi_xfer_tx_buf[2],
               device_control_ctx->status_buffer,
               device_control_ctx->status_buffer_len);
    }
     
    spi_slave_xfer_prepare(ctx, spi_xfer_rx_buf, SPI_XFER_RX_SIZE, spi_xfer_tx_buf, SPI_XFER_TX_SIZE);
}

RTOS_SPI_SLAVE_CALLBACK_ATTR
void device_control_spi_xfer_done_cb(rtos_spi_slave_t *ctx,
                                     device_control_t *device_control_ctx)
{
    uint8_t *rx_buf, *tx_buf;
    size_t rx_len, tx_len;
    size_t num_response_bytes = 1;

    spi_slave_xfer_complete(ctx, (void **)&rx_buf, &rx_len, (void **)&tx_buf, &tx_len, 0);
    control_ret_t ret = CONTROL_SUCCESS;

    if(rx_buf == &spi_xfer_rx_default_buf[0])
    {
        // xfer completed in default buffer. Ignore
        return;
    }

    spi_xfer_count++;
    rtos_printf(
        "SPI DC xfer %lu: len=%u hdr=%02x %02x %02x bytes=%02x %02x %02x %02x %02x %02x %02x %02x\n",
        (unsigned long)spi_xfer_count,
        (unsigned)rx_len,
        rx_len > 0 ? rx_buf[0] : 0,
        rx_len > 1 ? rx_buf[1] : 0,
        rx_len > 2 ? rx_buf[2] : 0,
        rx_len > 0 ? rx_buf[0] : 0,
        rx_len > 1 ? rx_buf[1] : 0,
        rx_len > 2 ? rx_buf[2] : 0,
        rx_len > 3 ? rx_buf[3] : 0,
        rx_len > 4 ? rx_buf[4] : 0,
        rx_len > 5 ? rx_buf[5] : 0,
        rx_len > 6 ? rx_buf[6] : 0,
        rx_len > 7 ? rx_buf[7] : 0);

    if(rx_len < 3)
    {
        // Received packet length has to be atleast 3
        ret = CONTROL_MALFORMED_PACKET;
    } else if ((rx_buf[0] == 0) && (rx_buf[1] == 0) && (rx_buf[2] == 0)) {
        // This is a NOP sent for reading tx_buf updated in the previous command.
    }
    else
    {
        ret = device_control_request(device_control_ctx,
                                rx_buf[0],
                                rx_buf[1],
                                rx_buf[2]);
        if( ret == CONTROL_SUCCESS ){    
            rx_len -= 3;
            device_control_payload_transfer_bidir(device_control_ctx, &rx_buf[3], rx_len, tx_buf, &num_response_bytes);
        }
    }
    
    // no response payload, only return status
    if( num_response_bytes == 1){
        //include device control status buffer into response
        spi_xfer_tx_buf[0] = 1;
        spi_xfer_tx_buf[1] = ret;
        memset(&spi_xfer_tx_buf[2], 0, SPI_XFER_TX_SIZE - 2 );
        memcpy(&spi_xfer_tx_buf[2], device_control_ctx->status_buffer, device_control_ctx->status_buffer_len );
    }
    spi_slave_xfer_prepare(ctx, spi_xfer_rx_buf, SPI_XFER_RX_SIZE, spi_xfer_tx_buf, SPI_XFER_TX_SIZE);
}
