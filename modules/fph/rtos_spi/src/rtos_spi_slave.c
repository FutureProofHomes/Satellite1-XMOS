// Copyright 2021-2023 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

#define DEBUG_UNIT RTOS_SPI

#include <string.h>
#include <xcore/triggerable.h>

#include "rtos_interrupt.h"
#include "rtos_spi_slave.h"

#define XFER_DONE_DEFAULT_BUF_CB_CODE   0
#define XFER_DONE_USER_BUF_CB_CODE      1

#define XFER_DONE_DEFAULT_BUF_CB_FLAG   (1 << XFER_DONE_DEFAULT_BUF_CB_CODE)
#define XFER_DONE_USER_BUF_CB_FLAG      (1 << XFER_DONE_USER_BUF_CB_CODE)

#define ALL_FLAGS (XFER_DONE_DEFAULT_BUF_CB_FLAG | XFER_DONE_USER_BUF_CB_FLAG)

#define CLRSR(c) asm volatile("clrsr %0" : : "n"(c));

#ifndef RTOS_SPI_SLAVE_XFER_DONE_QUEUE_SIZE
/* A default value of 2 allows an application and default buffer 
 * transaction to be captured before risk of corrupting data 
 * A value greater than 2 would have no impact on the driver, as
 * the next transfer would still overwrite the default buffer.
 * A value of 1 would
 */
#define RTOS_SPI_SLAVE_XFER_DONE_QUEUE_SIZE 2
#endif

DEFINE_RTOS_INTERRUPT_CALLBACK(rtos_spi_slave_isr, arg)
{
    rtos_spi_slave_t *ctx = arg;
    int isr_action;
    xfer_done_queue_item_t item;

    isr_action = s_chan_in_byte(ctx->c.end_b);

    switch(isr_action) {
        default: /* Default to default */
        case XFER_DONE_DEFAULT_BUF_CB_CODE:
            item.out_buf = ctx->default_out_buf;
            item.bytes_written = ctx->default_bytes_written;
            item.in_buf = ctx->default_in_buf;
            item.bytes_read = ctx->default_bytes_read;
            break;
        case XFER_DONE_USER_BUF_CB_CODE:
            item.out_buf = ctx->out_buf;
            item.bytes_written = ctx->bytes_written;
            item.in_buf = ctx->in_buf;
            item.bytes_read = ctx->bytes_read;
            break;
    }

    if (rtos_osal_queue_send(&ctx->xfer_done_queue, &item, RTOS_OSAL_NO_WAIT) == RTOS_OSAL_SUCCESS) {
        if (ctx->xfer_done != NULL) {
            /*
             * TODO: FIXME, FreeRTOS specific, not using OSAL here
             */
            xTaskNotifyGive(ctx->app_thread.thread);
        }
    } else {
        rtos_printf("Lost SPI slave transfer\n");
    }
}

void slave_transaction_started(rtos_spi_slave_t *ctx, uint8_t **out_buf, size_t *outbuf_len, uint8_t **in_buf, size_t *inbuf_len)
{
    if (ctx->user_data_ready) {
        rtos_printf("Slave transaction started with user data\n");
        *out_buf = ctx->out_buf;
        *outbuf_len = ctx->outbuf_len;
        *in_buf = ctx->in_buf;
        *inbuf_len = ctx->inbuf_len;
        ctx->user_data_ready = 0;
        rtos_printf("item to write %d, to read %d\n", ctx->outbuf_len, ctx->inbuf_len);

    } else {
        rtos_printf("Slave transaction started with default data\n");
        *out_buf = ctx->default_out_buf;
        *outbuf_len = ctx->default_outbuf_len;
        *in_buf = ctx->default_in_buf;
        *inbuf_len = ctx->default_inbuf_len;
    }
}

void slave_transaction_ended(rtos_spi_slave_t *ctx, uint8_t **out_buf, size_t bytes_written, uint8_t **in_buf, size_t bytes_read, size_t read_bits)
{
    if(!bytes_written)
    {
        return;
    }
    if ((*out_buf == ctx->default_out_buf) && (*in_buf == ctx->default_in_buf)) {
        ctx->default_bytes_written = bytes_written;
        ctx->default_bytes_read = bytes_read;
        rtos_printf("default transaction ended\n");
        if (!(ctx->drop_default_buffers)) {
            s_chan_out_byte(ctx->c.end_a, XFER_DONE_DEFAULT_BUF_CB_CODE);
        }
    } else {
        ctx->bytes_written = bytes_written;
        ctx->bytes_read = bytes_read;
        rtos_printf("app transaction ended\n");
        s_chan_out_byte(ctx->c.end_a, XFER_DONE_USER_BUF_CB_CODE);
    }
}

void spi_slave_default_buf_xfer_ended_disable(rtos_spi_slave_t *ctx) {
    ctx->drop_default_buffers = 1;
}

void spi_slave_default_buf_xfer_ended_enable(rtos_spi_slave_t *ctx) {
    ctx->drop_default_buffers = 0;
}

static void spi_slave_hil_thread(rtos_spi_slave_t *ctx)
{
    spi_slave_callback_group_t spi_cbg = {
        .slave_transaction_started = (slave_transaction_started_t) slave_transaction_started,
        .slave_transaction_ended = (slave_transaction_ended_t) slave_transaction_ended,
        .app_data = ctx,
    };

    if (ctx->start != NULL) {
        (void) s_chan_in_byte(ctx->c.end_a);
    }

    rtos_printf("SPI slave on tile %d core %d\n", THIS_XCORE_TILE, rtos_core_id_get());

    /*
     * spi_slave() will re-enable.
     */
    rtos_interrupt_mask_all();

    uint32_t hil_thread_mode = 0;
    
#if HIL_IO_SPI_SLAVE_HIGH_PRIO
    hil_thread_mode |= thread_mode_high_priority; // Enable high priority
#endif
#if HIL_IO_SPI_SLAVE_FAST_MODE
    hil_thread_mode |= thread_mode_fast; // Enable fast mode
#endif

    /*
     * spi_slave() itself uses interrupts, and does re-enable them. However,
     * it assumes that KEDI is not set, therefore it is cleared here.
     */
    CLRSR(XS1_SR_KEDI_MASK);

    spi_slave(
            &spi_cbg,
            ctx->p_sclk,
            ctx->p_mosi,
            ctx->p_miso,
            ctx->p_cs,
            ctx->clock_block,
            ctx->cpol,
            ctx->cpha,
            hil_thread_mode);
}

static void spi_slave_app_thread(rtos_spi_slave_t *ctx)
{
    uint32_t core_exclude_map;
    if (ctx->start != NULL) {
        ctx->start(ctx, ctx->app_data);
        /* Ensure that the SPI interrupt is enabled on the requested core */
        rtos_osal_thread_core_exclusion_get(NULL, &core_exclude_map);
        rtos_osal_thread_core_exclusion_set(NULL, ~(1 << ctx->interrupt_core_id));
        triggerable_enable_trigger(ctx->c.end_b);
        /* Restore the core exclusion map for the calling thread */
        rtos_osal_thread_core_exclusion_set(NULL, core_exclude_map);

        s_chan_out_byte(ctx->c.end_b, 0);
    }

    for (;;) {
        /*
         * TODO: FIXME, FreeRTOS specific, not using OSAL here
         */
        ulTaskNotifyTake(pdTRUE, RTOS_OSAL_WAIT_FOREVER);

        if (ctx->xfer_done != NULL) {
            ctx->xfer_done(ctx, ctx->app_data);
        }
    }
}

void spi_slave_xfer_prepare(rtos_spi_slave_t *ctx, void *rx_buf, size_t rx_buf_len, void *tx_buf, size_t tx_buf_len)
{
    ctx->in_buf = rx_buf;
    ctx->inbuf_len = rx_buf_len;
    ctx->out_buf = tx_buf;
    ctx->outbuf_len = tx_buf_len;
    ctx->user_data_ready = 1;
}

void spi_slave_xfer_prepare_default_buffers(rtos_spi_slave_t *ctx, void *rx_buf, size_t rx_buf_len, void *tx_buf, size_t tx_buf_len)
{
    ctx->default_in_buf = rx_buf;
    ctx->default_inbuf_len = rx_buf_len;
    ctx->default_out_buf = tx_buf;
    ctx->default_outbuf_len = tx_buf_len;
}

int spi_slave_xfer_complete(rtos_spi_slave_t *ctx, void **rx_buf, size_t *rx_len, void **tx_buf, size_t *tx_len, unsigned timeout)
{
    xfer_done_queue_item_t item;

    if (rtos_osal_queue_receive(&ctx->xfer_done_queue, &item, timeout) == RTOS_OSAL_SUCCESS) {
        *rx_buf = item.in_buf;
        *rx_len = item.bytes_read;
        *tx_buf = item.out_buf;
        *tx_len = item.bytes_written;

        return 0;
    } else {
        return -1;
    }
}

void rtos_spi_slave_start(
        rtos_spi_slave_t *spi_slave_ctx,
        void *app_data,
        rtos_spi_slave_start_cb_t start,
        rtos_spi_slave_xfer_done_cb_t xfer_done,
        unsigned interrupt_core_id,
        unsigned priority)
{
    spi_slave_ctx->app_data = app_data;
    spi_slave_ctx->start = start;
    spi_slave_ctx->xfer_done = xfer_done;
    spi_slave_ctx->interrupt_core_id = interrupt_core_id;

    rtos_osal_queue_create(&spi_slave_ctx->xfer_done_queue, "spi_slave_queue", RTOS_SPI_SLAVE_XFER_DONE_QUEUE_SIZE, sizeof(xfer_done_queue_item_t));

    if (start != NULL || xfer_done != NULL) {
        rtos_osal_thread_create(
                &spi_slave_ctx->app_thread,
                "spi_slave_app_thread",
                (rtos_osal_entry_function_t) spi_slave_app_thread,
                spi_slave_ctx,
                RTOS_THREAD_STACK_SIZE(spi_slave_app_thread),
                priority);
    }
}

void rtos_spi_slave_init(
        rtos_spi_slave_t *spi_slave_ctx,
        uint32_t io_core_mask,
        xclock_t clock_block,
        int cpol,
        int cpha,
        port_t p_sclk,
        port_t p_mosi,
        port_t p_miso,
        port_t p_cs)
{
    memset(spi_slave_ctx, 0, sizeof(rtos_spi_slave_t));

    spi_slave_ctx->clock_block = clock_block;
    spi_slave_ctx->cpol = cpol;
    spi_slave_ctx->cpha = cpha;
    spi_slave_ctx->p_sclk = p_sclk;
    spi_slave_ctx->p_mosi = p_mosi;
    spi_slave_ctx->p_miso = p_miso;
    spi_slave_ctx->p_cs = p_cs;
    spi_slave_ctx->c = s_chan_alloc();

    triggerable_setup_interrupt_callback(spi_slave_ctx->c.end_b, spi_slave_ctx, RTOS_INTERRUPT_CALLBACK(rtos_spi_slave_isr));

    rtos_osal_thread_create(
            &spi_slave_ctx->hil_thread,
            "spi_slave_hil_thread",
            (rtos_osal_entry_function_t) spi_slave_hil_thread,
            spi_slave_ctx,
            RTOS_THREAD_STACK_SIZE(spi_slave_hil_thread),
            RTOS_OSAL_HIGHEST_PRIORITY);

    /* Ensure the SPI thread is never preempted */
    rtos_osal_thread_preemption_disable(&spi_slave_ctx->hil_thread);
    /* And ensure it only runs on one of the specified cores */
    rtos_osal_thread_core_exclusion_set(&spi_slave_ctx->hil_thread, ~io_core_mask);
}
