// Copyright 2020-2023 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

#include <platform.h>

#include "rtos_rpc.h"
#include "rtos_i2s.h"

#if !defined(I2S_TILE_NO) || !defined(FPH_I2S_TX0_FRAMES)
#error "The board must define the I2S host tile and fixed TX0 frame count"
#endif

#if ON_TILE(I2S_TILE_NO)
#define I2S_RPC_FIXED_TX0_HOST 1
#endif

enum {
    fcode_rx,
    fcode_tx,
};

#ifdef I2S_RPC_FIXED_TX0_HOST
enum {
    TX0_RPC_PARAM_COUNT = 6,
    TX0_RPC_SAMPLE_COUNT = FPH_I2S_TX0_FRAMES * 2,
    TX0_RPC_REQUEST_BYTES =
        2 * sizeof(int) + TX0_RPC_PARAM_COUNT * sizeof(rpc_param_desc_t) +
        sizeof(rtos_i2s_t *) + sizeof(size_t) + sizeof(unsigned) + sizeof(int) +
        TX0_RPC_SAMPLE_COUNT * sizeof(int32_t),
};

typedef struct {
    int fcode, param_count;
    rpc_param_desc_t params[TX0_RPC_PARAM_COUNT];
    rtos_i2s_t *ctx;
    int32_t samples[TX0_RPC_SAMPLE_COUNT];
    size_t frame_count;
    unsigned timeout;
    int out_select;
} tx0_rpc_request_t;

_Static_assert(sizeof(tx0_rpc_request_t) == TX0_RPC_REQUEST_BYTES,
               "TX0 request must match the packed RPC layout");

/* The single remote client submits one fixed-size stereo TX0 block at a time. */
static _Alignas(8) tx0_rpc_request_t tx0_rpc_request;
static rtos_i2s_t *tx0_rpc_host_ctx;

static void parse_fixed_tx0_request(rpc_msg_t *rpc_msg, tx0_rpc_request_t *request)
{
    if (request->ctx != tx0_rpc_host_ctx ||
        request->fcode != fcode_tx || request->param_count != TX0_RPC_PARAM_COUNT ||
        request->out_select != 0 || request->frame_count != FPH_I2S_TX0_FRAMES) {
        __builtin_trap();
    }

    static const rpc_param_desc_t expected[] = {
        {sizeof(rtos_i2s_t *), 0, 1, 0},
        {TX0_RPC_SAMPLE_COUNT * sizeof(int32_t), 1, 1, 0},
        {sizeof(size_t), 0, 1, 0},
        {sizeof(unsigned), 0, 1, 0},
        {sizeof(int), 0, 1, 0},
        RPC_PARAM_RETURN(size_t),
    };
    _Static_assert(sizeof(expected) / sizeof(expected[0]) == TX0_RPC_PARAM_COUNT,
                   "TX0 request descriptor count");
    for (size_t i = 0; i < TX0_RPC_PARAM_COUNT; ++i) {
        const rpc_param_desc_t *param = &request->params[i];
        if (param->length != expected[i].length || param->ptr != expected[i].ptr ||
            param->input != expected[i].input || param->output != expected[i].output) {
            __builtin_trap();
        }
    }
    rpc_request_parse(rpc_msg, (uint8_t *)request);
}
#endif

__attribute__((fptrgroup("rtos_i2s_rx_fptr_grp")))
static size_t i2s_remote_rx(
        rtos_i2s_t *ctx,
        int32_t *i2s_sample_buf,
        size_t frame_count,
        unsigned timeout)
{
    rtos_intertile_address_t *host_address = &ctx->rpc_config->host_address;
    rtos_i2s_t *host_ctx_ptr = ctx->rpc_config->host_ctx_ptr;
    size_t ret;

    const rpc_param_desc_t rpc_param_desc[] = {
            RPC_PARAM_TYPE(ctx),
            RPC_PARAM_OUT_BUFFER(i2s_sample_buf, frame_count * (2 * ctx->num_in)),
            RPC_PARAM_TYPE(frame_count),
            RPC_PARAM_TYPE(timeout),
            RPC_PARAM_RETURN(size_t),
            RPC_PARAM_LIST_END
    };

    rtos_osal_mutex_get(&ctx->mutex, RTOS_OSAL_WAIT_FOREVER);

    rpc_client_call_generic(
            host_address->intertile_ctx, host_address->port, fcode_rx, rpc_param_desc,
            &host_ctx_ptr, i2s_sample_buf, &frame_count, &timeout, &ret);

    rtos_osal_mutex_put(&ctx->mutex);

    return ret;
}

__attribute__((fptrgroup("rtos_i2s_tx_fptr_grp")))
static size_t i2s_remote_tx(
        rtos_i2s_t *ctx,
        int32_t *i2s_sample_buf,
        size_t frame_count,
        unsigned timeout)
{
    rtos_intertile_address_t *host_address = &ctx->rpc_config->host_address;
    rtos_i2s_t *host_ctx_ptr = ctx->rpc_config->host_ctx_ptr;
    size_t ret;
    int out_select = 0;
    const rpc_param_desc_t rpc_param_desc[] = {
            RPC_PARAM_TYPE(ctx),
            RPC_PARAM_IN_BUFFER(i2s_sample_buf, frame_count * 2),
            RPC_PARAM_TYPE(frame_count),
            RPC_PARAM_TYPE(timeout),
            RPC_PARAM_TYPE(out_select),
            RPC_PARAM_RETURN(size_t),
            RPC_PARAM_LIST_END
    };

    rtos_osal_mutex_get(&ctx->mutex, RTOS_OSAL_WAIT_FOREVER);

    rpc_client_call_generic(
            host_address->intertile_ctx, host_address->port, fcode_tx, rpc_param_desc,
            &host_ctx_ptr, i2s_sample_buf, &frame_count, &timeout, &out_select, &ret);

    rtos_osal_mutex_put(&ctx->mutex);

    return ret;
}

__attribute__((fptrgroup("rtos_i2s_tx_fptr_grp")))
static size_t i2s_remote_1_tx(
        rtos_i2s_t *ctx,
        int32_t *i2s_sample_buf,
        size_t frame_count,
        unsigned timeout)
{
    rtos_intertile_address_t *host_address = &ctx->rpc_config->host_address;
    rtos_i2s_t *host_ctx_ptr = ctx->rpc_config->host_ctx_ptr;
    size_t ret;
    int out_select = 1;
    const rpc_param_desc_t rpc_param_desc[] = {
            RPC_PARAM_TYPE(ctx),
            RPC_PARAM_IN_BUFFER(i2s_sample_buf, frame_count * 2),
            RPC_PARAM_TYPE(frame_count),
            RPC_PARAM_TYPE(timeout),
            RPC_PARAM_TYPE(out_select),
            RPC_PARAM_RETURN(size_t),
            RPC_PARAM_LIST_END
    };

    rtos_osal_mutex_get(&ctx->mutex, RTOS_OSAL_WAIT_FOREVER);

    rpc_client_call_generic(
            host_address->intertile_ctx, host_address->port, fcode_tx, rpc_param_desc,
            &host_ctx_ptr, i2s_sample_buf, &frame_count, &timeout, &out_select, &ret);

    rtos_osal_mutex_put(&ctx->mutex);

    return ret;
}


#ifndef I2S_RPC_FIXED_TX0_HOST
static int i2s_rx_rpc_host(rpc_msg_t *rpc_msg, uint8_t **resp_msg)
{
    int msg_length;

    rtos_i2s_t *i2s_ctx;
    int32_t *i2s_sample_buf;
    size_t frame_count;
    unsigned timeout;
    size_t ret;
    
    /* Here, because the buffer is output only, the buffer
    pointer will not get set. */
    rpc_request_unmarshall(
            rpc_msg,
            &i2s_ctx, &i2s_sample_buf, &frame_count, &timeout, &ret);

    /* Instead allocate a buffer with the length parameter
    before calling, as this is what would be done by
    the client. */
    i2s_sample_buf = rtos_osal_malloc(frame_count * (2 * i2s_ctx->num_out) * sizeof(i2s_sample_buf[0]));

    ret = rtos_i2s_rx(i2s_ctx, i2s_sample_buf, frame_count, timeout);

    msg_length = rpc_response_marshall(
            resp_msg, rpc_msg,
            i2s_ctx, i2s_sample_buf, frame_count, timeout, ret);

    /* The data from buffer has been copied into the response
    message. Since buffer was allocated on the heap, free
    it now. */
    rtos_osal_free(i2s_sample_buf);

    return msg_length;
}
#endif

static int i2s_tx_rpc_host(rpc_msg_t *rpc_msg, uint8_t **resp_msg)
{
    int msg_length;

    rtos_i2s_t *i2s_ctx;
    int32_t *i2s_sample_buf;
    size_t frame_count;
    unsigned timeout;
    size_t ret;
    int out_select;

    rpc_request_unmarshall(
            rpc_msg,
            &i2s_ctx, &i2s_sample_buf, &frame_count, &timeout, &out_select, &ret);

    if( out_select == 0 ){
        ret = rtos_i2s_tx(i2s_ctx, i2s_sample_buf, frame_count, timeout);
    }
    else {
        ret = rtos_i2s_tx_1(i2s_ctx, i2s_sample_buf, frame_count, timeout);
    }

    msg_length = rpc_response_marshall(
            resp_msg, rpc_msg,
            i2s_ctx, i2s_sample_buf, frame_count, timeout, ret);

    return msg_length;
}

static void i2s_rpc_thread(rtos_intertile_address_t *client_address)
{
    int msg_length;
    uint8_t *resp_msg;
    rpc_msg_t rpc_msg;
    rtos_intertile_t *intertile_ctx = client_address->intertile_ctx;
    uint8_t intertile_port = client_address->port;

    for (;;) {
#ifdef I2S_RPC_FIXED_TX0_HOST
        size_t request_length = rtos_intertile_rx_len(intertile_ctx, intertile_port, RTOS_OSAL_WAIT_FOREVER);
        /* Both tiles are built together; any other length is a protocol fault. */
        if (request_length != sizeof(tx0_rpc_request)) {
            __builtin_trap();
        }
        rtos_intertile_rx_data(intertile_ctx, &tx0_rpc_request, sizeof(tx0_rpc_request));
        parse_fixed_tx0_request(&rpc_msg, &tx0_rpc_request);
        msg_length = i2s_tx_rpc_host(&rpc_msg, &resp_msg);
#else
        /* receive RPC request message from client */
        uint8_t *req_msg;
        msg_length = rtos_intertile_rx(intertile_ctx, intertile_port, (void **) &req_msg, RTOS_OSAL_WAIT_FOREVER);

        rpc_request_parse(&rpc_msg, req_msg);

        switch (rpc_msg.fcode) {
        case fcode_rx:
            msg_length = i2s_rx_rpc_host(&rpc_msg, &resp_msg);
            break;
        case fcode_tx:
            msg_length = i2s_tx_rpc_host(&rpc_msg, &resp_msg);
            break;
        }

        rtos_osal_free(req_msg);
#endif

        /* send RPC response message to client */
        rtos_intertile_tx(intertile_ctx, intertile_port, resp_msg, msg_length);
        rtos_osal_free(resp_msg);
    }
}

__attribute__((fptrgroup("rtos_driver_rpc_host_start_fptr_grp")))
static void i2s_rpc_start(
        rtos_driver_rpc_t *rpc_config)
{
    xassert(rpc_config->host_task_priority >= 0);

    for (int i = 0; i < rpc_config->remote_client_count; i++) {

        rtos_intertile_address_t *client_address = &rpc_config->client_address[i];

        xassert(client_address->port >= 0);

        rtos_osal_thread_create(
                NULL,
                "i2s_rpc_thread",
                (rtos_osal_entry_function_t) i2s_rpc_thread,
                client_address,
                RTOS_THREAD_STACK_SIZE(i2s_rpc_thread),
                rpc_config->host_task_priority);
    }
}

void rtos_i2s_rpc_config(
        rtos_i2s_t *i2s_ctx,
        unsigned intertile_port,
        unsigned host_task_priority)
{
    rtos_driver_rpc_t *rpc_config = i2s_ctx->rpc_config;

    if (rpc_config->remote_client_count == 0) {
        /* This is a client */
        rpc_config->host_address.port = intertile_port;

        rtos_osal_mutex_create(&i2s_ctx->mutex, "i2s_lock", RTOS_OSAL_NOT_RECURSIVE);

    } else {
        for (int i = 0; i < rpc_config->remote_client_count; i++) {
            rpc_config->client_address[i].port = intertile_port;
        }
        rpc_config->host_task_priority = host_task_priority;
    }
}

void rtos_i2s_rpc_client_init(
        rtos_i2s_t *i2s_ctx,
        rtos_driver_rpc_t *rpc_config,
        rtos_intertile_t *host_intertile_ctx)
{
    i2s_ctx->rpc_config = rpc_config;
    i2s_ctx->rx = i2s_remote_rx;
    i2s_ctx->tx = i2s_remote_tx;
    rpc_config->rpc_host_start = NULL;
    rpc_config->remote_client_count = 0;
    rpc_config->host_task_priority = -1;

    /* This must be configured later with rtos_i2s_rpc_config() */
    rpc_config->host_address.port = -1;

    rpc_config->host_address.intertile_ctx = host_intertile_ctx;
    rpc_config->host_ctx_ptr = (void *) s_chan_in_word(host_intertile_ctx->c);
    i2s_ctx->num_out = s_chan_in_word(host_intertile_ctx->c);
    i2s_ctx->num_in = s_chan_in_word(host_intertile_ctx->c);

    if( i2s_ctx->num_out == 2){
        i2s_ctx->tx_1 = i2s_remote_1_tx;
    }
}

void rtos_i2s_rpc_host_init(
        rtos_i2s_t *i2s_ctx,
        rtos_driver_rpc_t *rpc_config,
        rtos_intertile_t *client_intertile_ctx[],
        size_t remote_client_count)
{
    xassert(i2s_ctx->is_slave == false);
#ifdef I2S_RPC_FIXED_TX0_HOST
    xassert(remote_client_count == 1 && tx0_rpc_host_ctx == NULL);
    tx0_rpc_host_ctx = i2s_ctx;
#endif

    i2s_ctx->rpc_config = rpc_config;
    rpc_config->rpc_host_start = i2s_rpc_start;
    rpc_config->remote_client_count = remote_client_count;

    /* This must be configured later with rtos_i2s_rpc_config() */
    rpc_config->host_task_priority = -1;

    for (int i = 0; i < remote_client_count; i++) {
        rpc_config->client_address[i].intertile_ctx = client_intertile_ctx[i];
        s_chan_out_word(client_intertile_ctx[i]->c, (uint32_t) i2s_ctx);
        s_chan_out_word(client_intertile_ctx[i]->c, (uint32_t) i2s_ctx->num_out);
        s_chan_out_word(client_intertile_ctx[i]->c, (uint32_t) i2s_ctx->num_in);

        /* This must be configured later with rtos_i2s_rpc_config() */
        rpc_config->client_address[i].port = -1;
    }
}
